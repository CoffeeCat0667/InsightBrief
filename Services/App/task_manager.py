# -*- coding: utf-8 -*-
"""抓取任务运行时: 线程池并发执行 + 事件发布 (内存缓冲 + Redis 快照) + SSE 订阅。

设计 (对照 DECISIONS.md):
- 抓取 = 人工前端触发, 无定时器; 任务由进程内 ThreadPoolExecutor 并发执行
- **SSE 唯一进度通道**: worker 线程 -> asyncio 队列 -> SSE; 事件与状态快照同步写入
  Redis, 断线/进程重启后新连接从 Redis 重放历史事件 (无轮询降级)
- 取消: 请求级 flag, 在源与源之间生效 (正在进行的源跑完即停)
- 单源失败不中断整批 (与 ingest 逐篇容错一致); 任务级意外异常 -> failed
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import redis

from .db import SessionLocal
from .models import CrawlRun, CrawlTask
from .schemas import TaskStatus

logger = logging.getLogger(__name__)

# Redis key / 保留期 (kind 命名空间: crawl/brief 任务 id 各自自增, key 必须隔离)
_EVENTS_KEY = "task:events:{kind}:{task_id}"
_SNAPSHOT_KEY = "task:snap:{kind}:{task_id}"
_TTL_SECONDS = 7 * 86400
_EVENT_TAIL = 1000
_HEARTBEAT_SECONDS = 15
KIND_CRAWL = "crawl"
KIND_BRIEF = "brief"


def _handle_key(task_id: int, kind: str) -> str:
    return f"{kind}:{task_id}"

_TERMINAL = frozenset(
    {
        TaskStatus.COMPLETED.value,
        TaskStatus.FAILED.value,
        TaskStatus.CANCELLED.value,
    }
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskManager:
    """任务注册表 + 事件总线 (模块唯一实例, lifespan 注入 event loop)。"""

    def __init__(self, max_workers: int = 4) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="crawl-worker"
        )
        self._lock = threading.Lock()
        self._handles: Dict[int, Dict[str, Any]] = {}
        self._subscribers: Dict[int, set] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._redis: Optional[redis.Redis] = None
        self._redis_tried = False

    # ---------------------------------------------------------- 生命周期
    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def recover_stale_tasks(self) -> int:
        """启动恢复: 进程重启后, 将滞留 pending/running 的孤儿任务标记为 failed。"""
        from .models import CrawlRun

        recovered = 0
        with SessionLocal() as session:
            stale = (
                session.query(CrawlTask)
                .filter(
                    CrawlTask.status.in_(
                        [TaskStatus.PENDING.value, TaskStatus.RUNNING.value]
                    )
                )
                .all()
            )
            for task in stale:
                task.status = TaskStatus.FAILED.value
                task.progress = 100
                task.finished_at = datetime.now(timezone.utc)
                task.error = {"message": "服务重启中断"}
                task.stage = None
                recovered += 1
                session.query(CrawlRun).filter(CrawlRun.task_id == task.id).update(
                    {
                        "status": TaskStatus.FAILED.value,
                        "error": {"message": "服务重启中断"},
                    }
                )
            if stale:
                session.commit()
        logger.warning("启动恢复: %d 个孤儿任务标记为 failed", recovered)
        return recovered

    def recover_stale_brief_tasks(self) -> int:
        """启动恢复 (简报任务): 滞留 pending/running 的孤儿简报任务标记 failed。"""
        from .models import BriefTask

        recovered = 0
        with SessionLocal() as session:
            stale = (
                session.query(BriefTask)
                .filter(
                    BriefTask.status.in_(
                        [TaskStatus.PENDING.value, TaskStatus.RUNNING.value]
                    )
                )
                .all()
            )
            for task in stale:
                task.status = TaskStatus.FAILED.value
                task.progress = 100
                task.finished_at = datetime.now(timezone.utc)
                task.error = {"message": "服务重启中断"}
                task.stage = None
                recovered += 1
            if stale:
                session.commit()
        logger.warning("启动恢复: %d 个孤儿简报任务标记为 failed", recovered)
        return recovered

    def shutdown(self) -> None:
        """进程退出: 停止接受新任务, 等待在跑任务收尾 (不中断抓取)。"""
        self._executor.shutdown(wait=True, cancel_futures=False)

    # ---------------------------------------------------------- Redis 访问
    def _get_redis(self) -> Optional[redis.Redis]:
        if self._redis_tried:
            return self._redis
        self._redis_tried = True
        try:
            from Config.config import db_config

            cfg = db_config()["redis"]
            client = redis.Redis(
                host=cfg["host"],
                port=cfg["port"],
                db=cfg.get("db", 0),
                password=cfg.get("password") or None,
                decode_responses=True,
                socket_timeout=2,
            )
            client.ping()
            self._redis = client
        except Exception as exc:
            logger.warning("Redis 不可用, SSE 断线重放降级为内存缓冲: %s", exc)
            self._redis = None
        return self._redis

    # ---------------------------------------------------------- 发布/订阅
    def publish(
        self,
        task_id: int,
        event: str,
        data: Dict[str, Any],
        kind: str = KIND_CRAWL,
    ) -> None:
        """发事件: 内存尾缓冲 + Redis 链 + 推送给该任务所有 SSE 订阅队列。

        kind: 任务类型命名空间 ("crawl"/"brief"), 防 id 冲突串流。
        """
        now = _utcnow()
        seq = 0
        key = _handle_key(task_id, kind)
        with self._lock:
            handle = self._handles.get(key)
            if handle is not None:
                seq = handle["seq"] = handle["seq"] + 1
                handle["events"].append(
                    {"seq": seq, "event": event, "data": data, "ts": now}
                )
                tail = handle["events"]
                if len(tail) > _EVENT_TAIL:
                    del tail[: len(tail) - _EVENT_TAIL]
            queues = list(self._subscribers.get(key, ()))
        payload = {"seq": seq, "event": event, "data": data, "ts": now}
        self._store_redis(task_id, payload, kind)
        if self._loop is not None:
            for q in queues:
                try:
                    self._loop.call_soon_threadsafe(q.put_nowait, payload)
                except RuntimeError:
                    pass  # 事件循环已关闭 (进程退出中)

    def _store_redis(self, task_id: int, payload: Dict[str, Any], kind: str) -> None:
        client = self._get_redis()
        if client is None:
            return
        try:
            with client.pipeline() as pipe:
                pipe.rpush(_EVENTS_KEY.format(kind=kind, task_id=task_id), json.dumps(payload, ensure_ascii=False))
                pipe.ltrim(_EVENTS_KEY.format(kind=kind, task_id=task_id), -_EVENT_TAIL, -1)
                pipe.expire(_EVENTS_KEY.format(kind=kind, task_id=task_id), _TTL_SECONDS)
                pipe.set(_SNAPSHOT_KEY.format(kind=kind, task_id=task_id), json.dumps(payload, ensure_ascii=False), ex=_TTL_SECONDS)
                pipe.execute()
        except Exception as exc:
            logger.warning("[task %s] Redis 写入失败: %s", task_id, exc)

    def subscribe(self, task_id: int, kind: str = KIND_CRAWL) -> "asyncio.Queue":
        q: asyncio.Queue = asyncio.Queue()
        key = _handle_key(task_id, kind)
        with self._lock:
            self._subscribers.setdefault(key, set()).add(q)
        return q

    def unsubscribe(self, task_id: int, queue: "asyncio.Queue", kind: str = KIND_CRAWL) -> None:
        key = _handle_key(task_id, kind)
        with self._lock:
            subs = self._subscribers.get(key)
            if subs:
                subs.discard(queue)
                if not subs:
                    self._subscribers.pop(key, None)

    def replay_events(self, task_id: int, kind: str = KIND_CRAWL) -> List[Dict[str, Any]]:
        """断线/重启重放: 优先 Redis 历史事件, 否则进程内尾缓冲。"""
        client = self._get_redis()
        if client is not None:
            try:
                raw = client.lrange(_EVENTS_KEY.format(kind=kind, task_id=task_id), 0, -1)
                if raw:
                    return [json.loads(entry) for entry in raw]
            except Exception as exc:
                logger.warning("[task %s] Redis 读取失败: %s", task_id, exc)
        key = _handle_key(task_id, kind)
        with self._lock:
            handle = self._handles.get(key)
            if handle is not None:
                return list(handle["events"])
        return []

    def is_active(self, task_id: int, kind: str = KIND_CRAWL) -> bool:
        key = _handle_key(task_id, kind)
        with self._lock:
            handle = self._handles.get(key)
            return handle is not None and handle["status"] not in _TERMINAL

    # ---------------------------------------------------------- 任务执行
    def dispatch(
        self,
        task_id: int,
        processor: Optional[Callable[[int], None]] = None,
        kind: str = KIND_CRAWL,
    ) -> None:
        """路由创建 DB 行后调用: 注册句柄并投入线程池。

        processor: 自定义任务执行器 (如简报 BriefProcessor); None 走默认
        crawl 抓取路径 (行为不变)。kind: 任务类型命名空间。
        """
        key = _handle_key(task_id, kind)
        with self._lock:
            self._handles[key] = {
                "status": TaskStatus.PENDING.value,
                "cancel": False,
                "seq": 0,
                "events": [],
            }
        self._executor.submit(self._run_task, task_id, processor, kind)

    def request_cancel(self, task_id: int, kind: str = KIND_CRAWL) -> bool:
        """请求取消; 返回 False 表示任务不存在或已终态 (由路由转 404/200)。"""
        key = _handle_key(task_id, kind)
        with self._lock:
            handle = self._handles.get(key)
            if handle is None or handle["status"] in _TERMINAL:
                return False
            handle["cancel"] = True
            return True

    def cancel_requested(self, task_id: int, kind: str = KIND_CRAWL) -> bool:
        """(处理器公开 API) 取消检查: 阶段间生效。"""
        return self._cancel_requested(task_id, kind)

    def _cancel_requested(self, task_id: int, kind: str = KIND_CRAWL) -> bool:
        key = _handle_key(task_id, kind)
        with self._lock:
            handle = self._handles.get(key)
            return bool(handle and handle["cancel"])

    def _run_task(
        self,
        task_id: int,
        processor: Optional[Callable[[int], None]] = None,
        kind: str = KIND_CRAWL,
    ) -> None:
        """worker 外壳: 执行处理器 (crawl 默认), 异常兜底 + 句柄清理。

        processor 必须自行保证终态写入与事件发布 (如 brief_failed);
        本外壳只在处理器自身抛异常时打日志 (滞留任务由启动恢复兜底)。
        """
        try:
            if processor is None:
                self._execute(task_id, kind)
            else:
                processor(task_id)
        except Exception as exc:
            logger.exception("[task %s] 任务执行异常", task_id)
            if processor is None:
                self._finalize(
                    task_id, TaskStatus.FAILED.value, error={"message": str(exc)}, kind=kind
                )
        finally:
            key = _handle_key(task_id, kind)
            with self._lock:
                self._handles.pop(key, None)

    def _execute(self, task_id: int, kind: str = KIND_CRAWL) -> None:
        with SessionLocal() as session:
            task = session.get(CrawlTask, task_id)
            if task is None:
                return
            task.status = TaskStatus.RUNNING.value
            task.started_at = datetime.now(timezone.utc)
            task.progress = 0
            task.message = "任务启动"
            session.commit()
            source_ids = list(task.source_ids) if task.source_ids else None
            max_items = task.max_items or 30
        self._emit(task_id, "task_update", self._snapshot(task_id), kind=kind)

        if source_ids is None:
            from sqlalchemy import select

            from .models import Source

            with SessionLocal() as session:
                source_ids = session.scalars(
                    select(Source.id).where(Source.enabled.is_(True))
                ).all()
        total = len(source_ids)
        done = 0
        aggregate = {
            "sources": {"total": total, "ok": 0, "failed": 0},
            "articles": {"discovered": 0, "inserted": 0, "existed": 0, "failed": 0},
        }
        for idx, sid in enumerate(source_ids):
            if self._cancel_requested(task_id, kind):
                break
            self._mark_run(task_id, sid, running=True)
            self._emit(task_id, "run_started", {"source_id": sid, "index": idx, "total_sources": total}, kind=kind)

            def on_run_progress(done: int, item_total: int, _sid=sid, _idx=idx):
                self._emit(
                    task_id,
                    "run_progress",
                    {
                        "source_id": _sid,
                        "index": _idx,
                        "total_sources": total,
                        "done": done,
                        "total": item_total,
                    },
                    kind=kind,
                )

            try:
                from .ingest import crawl_and_ingest

                stats = crawl_and_ingest(sid, max_items=max_items, on_progress=on_run_progress)
                run_status = TaskStatus.COMPLETED.value
                aggregate["sources"]["ok"] += 1
            except Exception as exc:
                logger.warning("[task %s] 源 %s 抓取失败: %s", task_id, sid, exc)
                stats = {"discovered": 0, "inserted": 0, "existed": 0, "failed": 0}
                run_status = TaskStatus.FAILED.value
                aggregate["sources"]["failed"] += 1
            for key in ("discovered", "inserted", "existed", "failed"):
                aggregate["articles"][key] += stats.get(key, 0)
            self._mark_run(task_id, sid, running=False, status=run_status, stats=stats)
            self._emit(task_id, "run_finished", {"source_id": sid, "status": run_status, "stats": stats}, kind=kind)
            done += 1
            with SessionLocal() as session:
                task = session.get(CrawlTask, task_id)
                if task is None:
                    return
                task.progress = int(done / total * 100) if total else 100
                task.stage = f"正在抓取 {sid} ({done}/{total})"
                task.stats = aggregate
                session.commit()
            self._emit(task_id, "task_update", self._snapshot(task_id), kind=kind)

        cancelled = self._cancel_requested(task_id, kind)
        final = TaskStatus.CANCELLED.value if cancelled else TaskStatus.COMPLETED.value
        self._finalize(task_id, final, stats=aggregate, kind=kind)

    def _finalize(
        self,
        task_id: int,
        status: str,
        *,
        error: Optional[Dict[str, Any]] = None,
        stats: Optional[Dict[str, Any]] = None,
        kind: str = KIND_CRAWL,
    ) -> None:
        key = _handle_key(task_id, kind)
        with self._lock:
            handle = self._handles.get(key)
            if handle is not None:
                handle["status"] = status
        with SessionLocal() as session:
            task = session.get(CrawlTask, task_id)
            if task is None:
                return
            task.status = status
            task.progress = 100
            task.finished_at = datetime.now(timezone.utc)
            task.stage = None
            task.stats = stats if stats is not None else task.stats
            if error is not None:
                task.error = error
                task.message = error.get("message", "任务失败")
            session.commit()
        self._emit(task_id, f"task_{status}", self._snapshot(task_id), kind=kind)

    def _mark_run(
        self,
        task_id: int,
        source_id: str,
        *,
        running: bool,
        status: str = "",
        stats: Optional[Dict[str, int]] = None,
    ) -> None:
        with SessionLocal() as session:
            if running:
                session.add(
                    CrawlRun(task_id=task_id, source_id=source_id, status="running")
                )
                session.commit()
                return
            run = (
                session.query(CrawlRun)
                .filter(
                    CrawlRun.task_id == task_id, CrawlRun.source_id == source_id
                )
                .order_by(CrawlRun.id.desc())
                .first()
            )
            if run is None:
                return
            run.status = status
            run.discovered_links = (stats or {}).get("discovered", 0)
            run.success_count = (stats or {}).get("inserted", 0)
            run.failed_count = (stats or {}).get("failed", 0)
            run.finished_at = datetime.now(timezone.utc)
            session.commit()

    # ---------------------------------------------------------- 快照/事件
    def _snapshot(self, task_id: int) -> Dict[str, Any]:
        """任务实时快照 (读 DB 行 + 最近 run 摘要), 作为事件/SSE 负载。"""
        with SessionLocal() as session:
            task = session.get(CrawlTask, task_id)
            if task is None:
                return {"task_id": task_id, "status": "unknown"}
            runs = [
                {
                    "source_id": r.source_id,
                    "status": r.status,
                    "discovered_links": r.discovered_links,
                    "success_count": r.success_count,
                    "failed_count": r.failed_count,
                    "error": r.error,
                }
                for r in (
                    session.query(CrawlRun)
                    .filter(CrawlRun.task_id == task_id)
                    .order_by(CrawlRun.id.asc())
                    .all()
                )
            ]
            return {
                "task_id": task.id,
                "status": task.status,
                "progress": task.progress,
                "stage": task.stage,
                "message": task.message,
                "stats": task.stats,
                "error": task.error,
                "source_ids": task.source_ids,
                "max_items": task.max_items,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "started_at": task.started_at.isoformat() if task.started_at else None,
                "finished_at": task.finished_at.isoformat() if task.finished_at else None,
                "runs": runs,
            }

    def _emit(
        self, task_id: int, event: str, data: Dict[str, Any], kind: str = KIND_CRAWL
    ) -> None:
        self.publish(task_id, event, data, kind=kind)


manager = TaskManager()