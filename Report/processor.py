# -*- coding: utf-8 -*-
"""简报处理器 — 编排 LLM 算子生成新闻简报 (方案 v5)。

执行流 (任务线程池内运行):
  读任务参数 → 查文章 → 分类(批+二分) → 摘要/标题翻译(并发, 逐篇降级兜底)
  → 按分类综述 → 落库 (briefs/brief_items/文章回写) → 终态事件

降级/全挂语义 (用户拍板):
- ArticleContentError (403 风控) → 单篇翻译兜底, 不计连续失败
- LLMServiceError 连续 ≥ quarantine_consecutive(3) → 立即 failed (上游不可用)
- 收尾: 全部文章均为服务级降级 → failed 兜底; 否则 completed (含全 403)
- 取消: 阶段间生效, 已完成条目仍落库, 终态 brief_cancelled
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from .llm import LLMError, get_llm_provider
from .operators import (
    ArticleDegraded,
    CancelledError,
    ClassifyOperator,
    ComposeOverviewOperator,
    OperatorContext,
    OverviewDegraded,
    SummarizeOperator,
    TranslateTitleOperator,
)

logger = logging.getLogger(__name__)

# 中文类别 -> 枚举值 (articles.category / briefs.category)
CATEGORY_CN_EN = {
    "政治": "politics",
    "经济": "economy",
    "文化": "culture",
    "科技": "technology",
}
CATEGORY_EN_CN = {v: k for k, v in CATEGORY_CN_EN.items()}
CATEGORY_EN_VALUES = frozenset(CATEGORY_CN_EN.values())
CATEGORY_OTHER = "other"
# 综述等 LLM 展示用映射: other -> 中文 "其他"
CATEGORY_LABEL = {CATEGORY_OTHER: "其他", **CATEGORY_EN_CN}

DEFAULT_QUARANTINE = 3
DEFAULT_CONCURRENCY = 4
DEFAULT_MAX_BATCH = 20

_SERVICE_TYPES = ("timeout", "rate_limited", "connection", "http_error", "bad_response")


class QuarantineError(Exception):
    """连续 LLMServiceError 达上限 → 任务立即失败。"""


def _session():
    from Services.App.db import SessionLocal

    return SessionLocal()


def _brief_task_model():
    from Services.App.models import BriefTask

    return BriefTask


def _brief_model():
    from Services.App.models import Brief

    return Brief


def _brief_item_model():
    from Services.App.models import BriefItem

    return BriefItem


class BriefProcessor:
    """简报任务执行器 (task_manager.dispatch 的 processor 参数)。"""

    def __init__(self) -> None:
        self._manager = None
        self._task_id: Optional[int] = None
        self._summarize = SummarizeOperator()
        self._translate_title = TranslateTitleOperator()
        self._overview = ComposeOverviewOperator()

    # ---------------------------------------------------------- 入口
    def __call__(self, task_id: int) -> None:
        from Services.App.task_manager import manager

        self._manager = manager
        self._task_id = task_id
        try:
            self._run(task_id)
        except QuarantineError as exc:
            self._fail(task_id, "upstream_error", str(exc))
        except LLMError as exc:
            self._fail(task_id, "upstream_error", f"LLM 不可用: {exc}")
        except CancelledError:
            self._finalize_cancelled(task_id)
        except Exception as exc:
            logger.exception("[brief %s] 简报生成异常", task_id)
            self._fail(task_id, "internal_error", str(exc))

    # ---------------------------------------------------------- 主流程
    def _run(self, task_id: int) -> None:
        provider = get_llm_provider()

        with _session() as session:
            task = session.get(_brief_task_model(), task_id)
            if task is None:
                return
            params = task.params or {}
            task.status = "running"
            task.started_at = datetime.now(timezone.utc)
            task.progress = 0
            task.message = "任务启动"
            session.commit()

        self._emit(task_id, "brief_update")
        articles = self._load_articles(params)
        total = len(articles)
        stats: Dict[str, Any] = {
            "total": total,
            "success": 0,
            "degraded": 0,
            "degraded_by": {},
            "categories": {},
            "overview_degraded": 0,
        }
        if total == 0:
            with _session() as session:
                task = session.get(_brief_task_model(), task_id)
                if task is not None:
                    task.message = "没有符合条件的文章"
                session.commit()
            self._set_terminal(task_id, "completed", stats=stats)
            self._emit(task_id, "brief_completed")
            return

        llm_cfg = self._llm_cfg()
        operators_cfg = llm_cfg.get("operators") or {}
        classify_cfg = operators_cfg.get("classify") or {}
        summarize_cfg = operators_cfg.get("summarize") or {}
        translate_cfg = operators_cfg.get("translate_title") or {}
        overview_cfg = operators_cfg.get("compose_overview") or {}
        ctx = OperatorContext(
            provider,
            categories=list(CATEGORY_CN_EN),
            emit=lambda *_a, **_k: None,
            cancel_check=lambda: self._cancel_requested(),
            stats=stats,
            summarize_max_tokens=int(summarize_cfg.get("max_tokens") or 0) or None,
            translate_title_max_tokens=int(translate_cfg.get("max_tokens") or 0) or None,
            overview_max_tokens=int(overview_cfg.get("max_tokens") or 0) or None,
        )
        classify = ClassifyOperator(
            batch_size=int(classify_cfg.get("max_batch") or 0) or DEFAULT_MAX_BATCH
        )
        guard = _Guard(
            int(llm_cfg.get("quarantine_consecutive", DEFAULT_QUARANTINE))
        )

        # -- 1. 分类 (批 + 二分递归; 单篇失败降级为 other)
        self._stage(task_id, "分类中", 0, total, 20)
        items = [
            {"idx": i, "article": a, "title": a.title, "text": self._article_text(a)}
            for i, a in enumerate(articles)
        ]
        idx_cat = classify(ctx, items)
        for it in items:
            it["category"] = CATEGORY_CN_EN.get(
                idx_cat.get(it["idx"]), CATEGORY_OTHER
            )
        # 分类阶段连续服务失败达上限 → 立即终止 (摘要段 guard 双保险)
        if stats.get("classify_service_failures", 0) >= guard.limit:
            raise QuarantineError(
                f"LLM 服务连续 {guard.limit} 次失败, 判定上游不可用, 终止任务"
            )
        self._stage(task_id, "分类完成", total, total, 30)

        # -- 2. 摘要 + 标题翻译 (并发; 逐篇降级兜底)
        concurrency = int(llm_cfg.get("concurrency", DEFAULT_CONCURRENCY))
        pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="brief-llm")
        cancelled = False
        try:
            futures = [pool.submit(self._process_one, ctx, guard, it) for it in items]
            done, not_done = wait(futures, return_when=FIRST_EXCEPTION)
            fault = next((f.exception() for f in done if f.exception() is not None), None)
            if fault is not None:
                for f in not_done:
                    f.cancel()
                if isinstance(fault, CancelledError):
                    cancelled = True
                elif isinstance(fault, QuarantineError):
                    raise fault
                else:
                    raise fault
            else:
                cancelled = any(f.cancelled() for f in futures)
        finally:
            pool.shutdown(wait=True, cancel_futures=False)
        if cancelled:
            raise CancelledError()
        self._stage(task_id, "摘要完成", total, total, 70)

        # -- 3. 综述 (按分类; 失败 → 该分类 summary=None)
        by_cat: Dict[str, List[Dict[str, Any]]] = {}
        for it in items:
            by_cat.setdefault(it["category"], []).append(it)
        briefs = []
        for cat, group in by_cat.items():
            self._check_cancel()
            briefs.append(self._compose_overview(ctx, cat, group, stats))
        self._stage(task_id, "综述完成", total, total, 90)

        # -- 4. 落库 + 终态
        self._finalize(task_id, briefs, items, stats)

    # ---------------------------------------------------------- 单篇处理
    def _process_one(
        self, ctx: OperatorContext, guard: "_Guard", item: Dict[str, Any]
    ) -> None:
        """单篇: 摘要 + 标题翻译; 任一步失败 → 整篇降级 (翻译兜底)。"""
        try:
            item["summary"] = self._summarize(ctx, item)
            item["title_cn"] = self._translate_title(ctx, item["title"])
            guard.touch(ok=True)
        except ArticleDegraded as degraded:
            item["degraded"] = degraded
            item["summary"] = None
            item["title_cn"] = item["title"]
            item["degraded_meta"] = {"degraded": degraded.degraded_type}
            self._translate_fallback(item)
            guard.touch(ok=False, service_error=degraded.service_error)
            if guard.quarantined():
                raise QuarantineError(
                    f"LLM 服务连续 {guard.limit} 次失败, 判定上游不可用, 终止任务"
                )

    def _translate_fallback(self, item: Dict[str, Any]) -> None:
        """降级兜底: 标题普通翻译; 非中文全文翻译写回文章 (均容错不抛)。"""
        title = item["title"]
        if not _is_chinese(title):
            try:
                item["title_cn"] = _translate(title)
            except Exception as exc:
                logger.warning("降级标题翻译失败: %s", exc)
        text = item.get("text") or ""
        if text and not _is_chinese(text):
            try:
                translated = _translate(text)
                if translated:
                    item["translated_content"] = translated
            except Exception as exc:
                logger.warning("降级全文翻译失败: %s", exc)

    def _compose_overview(
        self,
        ctx: OperatorContext,
        cat: str,
        group: List[Dict[str, Any]],
        stats: Dict[str, Any],
    ) -> Dict[str, Any]:
        """单分类综述; 失败 → OverviewDegraded: brief 保留但 summary=None。"""
        try:
            title, overview = self._overview(
                ctx,
                CATEGORY_LABEL.get(cat, cat),
                [
                    {"title": it.get("title_cn") or it["title"], "summary": it.get("summary")}
                    for it in group
                ],
            )
            return {"category": cat, "title": title, "summary": overview}
        except OverviewDegraded as exc:
            stats["overview_degraded"] += 1
            logger.warning("分类 %s 综述降级: %s", cat, exc.degraded_type)
            return {"category": cat, "title": None, "summary": None}

    # ---------------------------------------------------------- 数据
    def _load_articles(self, params: Dict[str, Any]) -> List[Any]:
        from sqlalchemy.orm import joinedload

        from Services.App.models import Article, Source

        stmt = (
            select(Article)
            # 预加载 contents, 防止 session 关闭后懒加载抛 DetachedInstanceError
            .options(joinedload(Article.contents))
            .join(Source, Article.source_id == Source.id)
            .where(Source.enabled.is_(True))
        )
        if params.get("source_ids"):
            stmt = stmt.where(Article.source_id.in_(params["source_ids"]))
        if params.get("category"):
            stmt = stmt.where(Article.category == params["category"])
        if params.get("start_time"):
            stmt = stmt.where(Article.crawled_at >= params["start_time"])
        if params.get("end_time"):
            stmt = stmt.where(Article.crawled_at <= params["end_time"])
        stmt = stmt.order_by(Article.crawled_at.desc(), Article.id.desc())
        with _session() as session:
            rows = session.scalars(stmt).unique().all()
        limit = int(params.get("max_items") or 0) or 200
        return list(rows[:limit])

    @staticmethod
    def _article_text(article: Any) -> str:
        if article.content:
            return article.content
        return "\n".join(c.content for c in article.contents)

    def _llm_cfg(self) -> Dict[str, Any]:
        from Services.App.models import SystemSetting

        with _session() as session:
            row = session.get(SystemSetting, "llm")
            return (row.value or {}) if row else {}

    # ---------------------------------------------------------- 状态/事件
    def _cancel_requested(self) -> bool:
        return bool(
            self._manager
            and self._manager.cancel_requested(self._task_id, kind="brief")
        )

    def _check_cancel(self) -> None:
        if self._cancel_requested():
            raise CancelledError()

    def _stage(self, task_id: int, stage: str, done: int, total: int, pct: int) -> None:
        with _session() as session:
            task = session.get(_brief_task_model(), task_id)
            if task is None:
                return
            task.stage = stage
            task.progress = min(99, pct)
            task.message = f"{stage} ({done}/{total})"
            session.commit()
        self._emit(task_id, "brief_update")

    def _snapshot(self, task_id: int) -> Dict[str, Any]:
        with _session() as session:
            task = session.get(_brief_task_model(), task_id)
            if task is None:
                return {"task_id": task_id, "status": "unknown"}
            brief_count = item_count = 0
            try:
                brief_count = session.query(_brief_model()).filter(
                    _brief_model().task_id == task_id
                ).count()
                item_count = (
                    session.query(_brief_item_model())
                    .join(_brief_model(), _brief_item_model().brief_id == _brief_model().id)
                    .filter(_brief_model().task_id == task_id)
                    .count()
                )
            except Exception:
                pass  # 0003 迁移前 brief_items.meta 列缺失时快照仍可用
            return {
                "task_id": task.id,
                "status": task.status,
                "progress": task.progress,
                "stage": task.stage,
                "message": task.message,
                "stats": task.stats,
                "error": task.error,
                "params": task.params,
                "brief_count": brief_count,
                "item_count": item_count,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "started_at": task.started_at.isoformat() if task.started_at else None,
                "finished_at": task.finished_at.isoformat() if task.finished_at else None,
            }

    def _emit(self, task_id: int, event: str) -> None:
        from Services.App.task_manager import manager

        manager.publish(task_id, event, self._snapshot(task_id), kind="brief")

    def _set_terminal(
        self,
        task_id: int,
        status: str,
        stats: Optional[Dict[str, Any]] = None,
        error: Optional[Dict[str, Any]] = None,
    ) -> None:
        with _session() as session:
            task = session.get(_brief_task_model(), task_id)
            if task is None:
                return
            task.status = status
            task.progress = 100
            task.finished_at = datetime.now(timezone.utc)
            task.stage = None
            if stats is not None:
                task.stats = stats
            if error is not None:
                task.error = error
                task.message = error.get("message", status)
            elif stats is not None:
                task.message = (
                    f"完成: {stats.get('success', 0)} 篇 / 共 {stats.get('total', 0)} 篇"
                )
            session.commit()

    def _fail(self, task_id: int, code: str, message: str) -> None:
        self._set_terminal(task_id, "failed", error={"code": code, "message": message})
        self._emit(task_id, "brief_failed")

    def _finalize_cancelled(self, task_id: int) -> None:
        self._set_terminal(task_id, "cancelled")
        self._emit(task_id, "brief_cancelled")

    # ---------------------------------------------------------- 落库
    def _finalize(
        self,
        task_id: int,
        briefs: List[Dict[str, Any]],
        items: List[Dict[str, Any]],
        stats: Dict[str, Any],
    ) -> None:
        """落库简报 + 文章回写。

        全挂语义 (用户拍板): 全部服务级降级时任务 failed, 但已产出的
        残料 (briefs/items/回写) **保留** — 与取消 (半成品不落库) 区分。
        """
        from Services.App.models import Article, Source

        with _session() as session:
            # source_id -> 真实源名 (S6: source_name 列存真名而非裸 id)
            source_names = {
                sid: name
                for sid, name in session.execute(
                    select(Source.id, Source.name)
                ).all()
            }
            task = session.get(_brief_task_model(), task_id)
            if task is None:
                return
            # 统计 + 文章回写 (分类/摘要/译文)
            for it in items:
                cat = it["category"]
                stats["categories"][cat] = stats["categories"].get(cat, 0) + 1
                art = session.get(Article, it["article"].id)
                degraded = it.get("degraded")
                if degraded is not None:
                    stats["degraded"] += 1
                    stats["degraded_by"][degraded.degraded_type] = (
                        stats["degraded_by"].get(degraded.degraded_type, 0) + 1
                    )
                    if art is not None:
                        if it.get("translated_content") and not art.translated_content:
                            art.translated_content = it["translated_content"]
                        if not art.category and cat in CATEGORY_EN_VALUES:
                            art.category = cat
                else:
                    stats["success"] += 1
                    if art is not None:
                        if not art.category and cat in CATEGORY_EN_VALUES:
                            art.category = cat
                        if it.get("summary") and not art.summary:
                            art.summary = it["summary"]
                        title_cn = it.get("title_cn")
                        if title_cn and title_cn != it["title"] and not art.translated_title:
                            art.translated_title = title_cn

            brief_models = []
            for b in briefs:
                bm = _brief_model()(
                    task_id=task_id,
                    category=b["category"] if b["category"] in CATEGORY_EN_VALUES else None,
                    title=b["title"],
                    summary=b["summary"],
                    stats={
                        "items": sum(1 for it in items if it["category"] == b["category"])
                    },
                    generated_at=datetime.now(timezone.utc),
                )
                session.add(bm)
                brief_models.append(bm)
            session.flush()
            for bm, b in zip(brief_models, briefs):
                for seq, it in enumerate(
                    [x for x in items if x["category"] == b["category"]]
                ):
                    meta = it.get("degraded_meta")
                    if meta is None and it.get("degraded") is not None:
                        meta = {"degraded": it["degraded"].degraded_type}
                    session.add(
                        _brief_item_model()(
                            brief_id=bm.id,
                            article_id=it["article"].id,
                            seq=seq,
                            title_cn=it.get("title_cn"),
                            summary=it.get("summary"),
                            category=it["category"]
                            if it["category"] in CATEGORY_EN_VALUES
                            else None,
                            source_name=source_names.get(it["article"].source_id)
                            or it["article"].source_id,
                            url=it["article"].url,
                            meta=meta,
                        )
                    )
            session.commit()

        # 全挂兜底: 全部文章均为服务级降级且无成功 → failed
        all_service_degraded = (
            stats["success"] == 0
            and stats["degraded"] == stats["total"]
            and stats["degraded_by"].get("content_policy", 0) == 0
            and sum(stats["degraded_by"].get(t, 0) for t in _SERVICE_TYPES) == stats["total"]
        )
        if all_service_degraded:
            self._fail(task_id, "upstream_error", "LLM 服务不可用: 全部文章处理失败")
            return
        self._set_terminal(task_id, "completed", stats=stats)
        self._emit(task_id, "brief_completed")


class _Guard:
    """连续 LLMServiceError 守卫 (并发安全)。"""

    def __init__(self, limit: int) -> None:
        self.limit = max(1, limit)
        self._counter = 0
        self._lock = threading.Lock()

    def touch(self, *, ok: bool, service_error: bool = False) -> None:
        with self._lock:
            self._counter = self._counter + 1 if service_error else 0

    def quarantined(self) -> bool:
        with self._lock:
            return self._counter >= self.limit


# ---------------------------------------------------------------- 翻译兜底

_translator = None
_translator_lock = threading.Lock()


def _translate(text: str) -> str:
    global _translator
    with _translator_lock:
        if _translator is None:
            from Services.translator import Translator

            kwargs: Dict[str, Any] = {}
            try:
                from Config.config import services_config

                tr = (services_config() or {}).get("translator") or {}
                if tr.get("chunk_size"):
                    kwargs["chunk_size"] = int(tr["chunk_size"])
            except Exception:
                pass
            _translator = Translator(**kwargs)
        translator = _translator
    return translator.translate(text)


def _is_chinese(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text[:200])