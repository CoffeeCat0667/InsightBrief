# -*- coding: utf-8 -*-
"""简报算子: 分类 / 摘要 / 标题翻译 / 综述 — 全部基于 LLMProvider.chat。

降级信号 (方案 v5):
- 单篇级: ArticleDegraded(degraded_type, service_error)
  * service_error=True   → 计入"连续 LLMServiceError"全挂判定
  * service_error=False  → 内容风控 (403), 不计全挂, 该篇翻译兜底
- 综述级: OverviewDegraded(degraded_type) → 该分类 brief 保留但 summary=None

分类批处理: 整批失败 → 二分拆批递归, 直至单篇执行 (每层失败均拆)。
"""
from __future__ import annotations

import logging
import random
import string
from typing import Any, Callable, Dict, List, Optional, Tuple

from .llm import ArticleContentError, LLMServiceError, LLMProvider
from .llm.base import ChatMessage
from .prompts import (
    CATEGORIES_DEFAULT,
    classify_messages,
    overview_messages,
    parse_classify,
    parse_overview,
    parse_summary,
    parse_title_cn,
    summarize_messages,
    translate_title_messages,
)

logger = logging.getLogger(__name__)

CATEGORY_OTHER = "其他"

# ---------------------------------------------------------------- signals

class ArticleDegraded(Exception):
    """单篇文章降级信号 (由算子抛出, 处理器捕获并走翻译兜底)。"""

    def __init__(
        self,
        degraded_type: str,
        *,
        service_error: bool,
        detail: Any = None,
    ) -> None:
        super().__init__(degraded_type)
        self.degraded_type = degraded_type
        self.service_error = service_error
        self.detail = detail


class OverviewDegraded(Exception):
    """综述降级信号 (该分类 brief 保留, summary=None)。"""

    def __init__(self, degraded_type: str, detail: Any = None) -> None:
        super().__init__(degraded_type)
        self.degraded_type = degraded_type
        self.detail = detail


DEGRADED_LABELS = {
    "timeout": "超时",
    "rate_limited": "限流",
    "connection": "连接失败",
    "http_error": "服务异常",
    "content_policy": "内容政策",
    "bad_response": "响应异常",
}


def _from_error(exc: LLMServiceError) -> ArticleDegraded:
    kind = getattr(exc, "kind", "http_error") or "http_error"
    if kind in ("connection", "timeout"):
        mapped = "connection" if kind == "connection" else "timeout"
    elif kind == "rate_limited":
        mapped = "rate_limited"
    else:
        mapped = "http_error"
    return ArticleDegraded(mapped, service_error=True, detail=str(exc))


# ---------------------------------------------------------------- context

class OperatorContext:
    """算子运行上下文 (处理器一次性构造, 逐算子共享统计)。"""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        categories: List[str],
        emit: Callable[[str, dict], None],
        cancel_check: Callable[[], bool],
        stats: Dict[str, Any],
        temperature: float = 0.3,
        summarize_max_tokens: Optional[int] = None,
        translate_title_max_tokens: Optional[int] = None,
        overview_max_tokens: Optional[int] = None,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        self.provider = provider
        self.categories = categories or CATEGORIES_DEFAULT
        self.emit = emit
        self.cancel_check = cancel_check
        self.stats = stats
        self.temperature = temperature
        self.summarize_max_tokens = summarize_max_tokens
        self.translate_title_max_tokens = translate_title_max_tokens
        self.overview_max_tokens = overview_max_tokens
        self.on_progress = on_progress or (lambda *_: None)

    def check_cancel(self) -> None:
        """阶段间取消检查 — 批前调用; 取消抛 CancelledError 终止算子链。"""
        if self.cancel_check():
            raise CancelledError()


class CancelledError(Exception):
    """任务取消信号 (处理器捕获 → 落库已完成条目 → cancelled 终态)。"""


# ---------------------------------------------------------------- 分类

class ClassifyOperator:
    """批分类 + 二分拆批 + 单篇兜底降级。"""

    def __init__(self, batch_size: int = 20) -> None:
        self._batch_size = max(1, batch_size)

    def __call__(
        self,
        ctx: OperatorContext,
        articles: List[Dict[str, Any]],
    ) -> Dict[int, str]:
        """articles: [{"idx": int, "title": str, "text": str, ...}] -> {idx: category}"""
        result: Dict[int, str] = {}
        batches = [
            articles[i : i + self._batch_size]
            for i in range(0, len(articles), self._batch_size)
        ]
        done = 0
        for batch in batches:
            ctx.check_cancel()
            for idx, cat in self._classify_batch(ctx, batch):
                result[idx] = cat
            done += len(batch)
            ctx.on_progress(done, len(articles))
        return result

    def _classify_batch(
        self, ctx: OperatorContext, items: List[Dict[str, Any]]
    ) -> List[Tuple[int, str]]:
        try:
            raw = ctx.provider.chat(
                classify_messages(items, ctx.categories), temperature=ctx.temperature
            )
            parsed = parse_classify(raw, ctx.categories)
            missing = [f"#{it['idx']}" for it in items if int(it["idx"]) not in parsed]
            if missing:
                raise LLMServiceError(
                    f"分类输出缺项 {missing}", kind="bad_response", detail=raw[:200]
                )
            return [(int(it["idx"]), parsed[int(it["idx"])]) for it in items]
        except CancelledError:
            raise
        except (LLMServiceError, ArticleContentError) as exc:
            return self._classify_split(ctx, items, exc)

    def _classify_split(
        self,
        ctx: OperatorContext,
        items: List[Dict[str, Any]],
        cause: Exception,
    ) -> List[Tuple[int, str]]:
        """整批失败 → 二分递归; 单篇失败 → 降级兜底。"""
        if len(items) <= 1:
            it = items[0]
            return [(int(it["idx"]), self._single_degraded_category(ctx, it, cause))]
        mid = len(items) // 2
        return self._classify_batch(ctx, items[:mid]) + self._classify_batch(ctx, items[mid:])

    def _single_degraded_category(
        self, ctx: OperatorContext, item: Dict[str, Any], cause: Exception
    ) -> str:
        """单篇分类失败 → 降级为 '其他' 继续 (不炸任务)。

        - 403 风控: 仅计数, 不入连续失败
        - LLM 服务错: 计入 classify_service_failures (处理器据此提前
          判定全挂), 摘要阶段 guard 会接力判定, 双重保障。
        """
        if isinstance(cause, ArticleContentError):
            ctx.stats.setdefault("classify_degraded", 0)
            ctx.stats["classify_degraded"] += 1
            return CATEGORY_OTHER
        if isinstance(cause, LLMServiceError):
            ctx.stats.setdefault("classify_degraded", 0)
            ctx.stats["classify_degraded"] += 1
            ctx.stats.setdefault("classify_service_failures", 0)
            ctx.stats["classify_service_failures"] += 1
            return CATEGORY_OTHER
        ctx.stats.setdefault("classify_degraded", 0)
        ctx.stats["classify_degraded"] += 1
        return CATEGORY_OTHER


# ---------------------------------------------------------------- 摘要/标题

class SummarizeOperator:
    def __call__(self, ctx: OperatorContext, item: Dict[str, Any]) -> str:
        ctx.check_cancel()
        try:
            raw = ctx.provider.chat(
                summarize_messages(item["title"], item.get("text") or ""),
                temperature=ctx.temperature,
                max_tokens=ctx.summarize_max_tokens,
            )
            return parse_summary(raw)
        except ArticleContentError as exc:
            raise ArticleDegraded("content_policy", service_error=False, detail=str(exc))
        except LLMServiceError as exc:
            raise _from_error(exc)


class TranslateTitleOperator:
    def __call__(self, ctx: OperatorContext, title: str) -> str:
        ctx.check_cancel()
        try:
            raw = ctx.provider.chat(
                translate_title_messages(title), temperature=ctx.temperature,
                max_tokens=ctx.translate_title_max_tokens,
            )
            return parse_title_cn(raw)
        except ArticleContentError as exc:
            raise ArticleDegraded("content_policy", service_error=False, detail=str(exc))
        except LLMServiceError as exc:
            raise _from_error(exc)


# ---------------------------------------------------------------- 综述

class ComposeOverviewOperator:
    def __call__(
        self, ctx: OperatorContext, category: str, items: List[Dict[str, Any]]
    ) -> Tuple[str, str]:
        ctx.check_cancel()
        try:
            raw = ctx.provider.chat(
                overview_messages(category, items), temperature=ctx.temperature,
                max_tokens=ctx.overview_max_tokens,
            )
            return parse_overview(raw)
        except ArticleContentError as exc:
            raise OverviewDegraded("content_policy", detail=str(exc))
        except LLMServiceError as exc:
            kind = getattr(exc, "kind", "http_error") or "http_error"
            raise OverviewDegraded(
                "connection" if kind == "connection" else (
                    "timeout" if kind == "timeout" else "http_error"
                ),
                detail=str(exc),
            )