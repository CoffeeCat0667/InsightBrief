# -*- coding: utf-8 -*-
"""抓取任务端点: 创建/列表/详情/取消 + SSE 进度事件流。"""
from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..models import BriefTask, CrawlTask, User
from ..schemas import CrawlTaskCreate, CrawlTaskRead, Page, PageParams, TaskCancelRead, TaskCancelRequest, ok
from ..schemas.task import TaskStatus
from ..security import get_current_user, require_admin
from ..task_manager import _HEARTBEAT_SECONDS, _TERMINAL, manager

router = APIRouter(prefix="/api/crawl-tasks", tags=["crawl-tasks"])
events_router = APIRouter(prefix="/api/tasks", tags=["crawl-tasks"])


@router.post("")
def create_crawl_task(
    body: CrawlTaskCreate,
    session: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """创建抓取任务 (人工触发); 与进行中任务源集合有交集时拒绝 (409)。

    源集合重叠语义: source_ids 省略/空 = 全部启用源 (全集); 全集与任何
    非空集合必重叠, 因此两边任一方为全集即视为冲突。
    """
    ids = [s for s in body.source_ids if s] if body.source_ids else []
    duplicates = [
        t
        for t in session.scalars(
            select(CrawlTask).where(
                CrawlTask.status.in_(
                    [TaskStatus.PENDING.value, TaskStatus.RUNNING.value]
                )
            )
        ).all()
        if not t.source_ids or not ids or set(t.source_ids) & set(ids)
    ]
    if duplicates:
        existing = duplicates[0]
        message = (
            f"全部源抓取已在进行中 (任务 {existing.id})"
            if not ids
            else f"源 {ids} 已在任务 {existing.id} 中抓取中"
            if existing.source_ids and set(existing.source_ids) & set(ids)
            else f"源集合与进行中任务 {existing.id} (全源) 重叠"
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "conflict", "message": message},
        )
    task = CrawlTask(
        user_id=user.id,
        status=TaskStatus.PENDING.value,
        source_ids=body.source_ids,
        max_items=body.max_items,
    )
    session.add(task)
    session.flush()
    session.commit()
    task = session.get(CrawlTask, task.id)
    manager.dispatch(task.id, kind="crawl")
    return ok(CrawlTaskRead.model_validate(task))


@router.get("")
def list_crawl_tasks(
    status: Optional[str] = None,
    page: PageParams = Depends(),
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """任务列表 (按创建时间倒序, 可选状态过滤, 不带 runs)。"""
    stmt = select(CrawlTask)
    if status:
        stmt = stmt.where(CrawlTask.status == status)
    total = (
        session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
        or 0
    )
    rows = (
        session.scalars(
            stmt.order_by(CrawlTask.id.desc())
            .offset((page.page - 1) * page.page_size)
            .limit(page.page_size)
        ).all()
    )
    items = [CrawlTaskRead.model_validate(r) for r in rows]
    return ok(Page[CrawlTaskRead](items=items, total=total, page=page.page, page_size=page.page_size))


@router.get("/{task_id}")
def get_crawl_task(
    task_id: int,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """任务详情 (含逐源运行明细 runs)。"""
    task = session.scalar(
        select(CrawlTask).options(joinedload(CrawlTask.runs)).where(CrawlTask.id == task_id)
    )
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"任务 {task_id} 不存在"},
        )
    return ok(CrawlTaskRead.model_validate(task))


@router.post("/{task_id}/cancel")
def cancel_crawl_task(
    task_id: int,
    body: Optional[TaskCancelRequest] = None,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """请求取消任务: 已终态返回当前状态 (requested=False), 否则标记取消。"""
    task = session.get(CrawlTask, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"任务 {task_id} 不存在"},
        )
    if task.status not in _TERMINAL and manager.request_cancel(task_id, kind="crawl"):
        session.refresh(task)
        return ok(
            TaskCancelRead(task_id=task_id, task_status=task.status, requested=True)
        )
    return ok(
        TaskCancelRead(task_id=task_id, task_status=task.status, requested=False)
    )


@events_router.get("/{task_id}/events")
async def task_event_stream(
    task_id: int,
    request: Request,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """SSE 进度通道: 先订阅再重放历史事件 (避免重放与订阅之间的丢事件
    窗口 — 重放循环的 await 让出事件循环时 publish 的事件, 既不在
    重放列表、也未入订阅队列而永久丢失); seq <= last_seq 去重兜底。
    """
    task = session.get(CrawlTask, task_id) or session.get(BriefTask, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"任务 {task_id} 不存在"},
        )
    kind = "brief" if isinstance(task, BriefTask) else "crawl"
    active = task.status not in _TERMINAL or manager.is_active(task_id, kind=kind)

    TERMINAL_EVENTS = {
        "task_completed",
        "task_failed",
        "task_cancelled",
        "brief_completed",
        "brief_failed",
        "brief_cancelled",
    }

    def fmt(ev: dict) -> str:
        return (
            f"event: {ev['event']}\n"
            f"data: {json.dumps(ev['data'], ensure_ascii=False)}\n\n"
        )

    async def generate():
        try:
            yield ": connected\n\n"
            # 先订阅: 重放期间的实时事件进入订阅队列, 由 seq 去重兜住
            queue = manager.subscribe(task_id, kind=kind)
            try:
                last_seq = 0
                for ev in manager.replay_events(task_id, kind=kind):
                    last_seq = max(last_seq, ev.get("seq") or 0)
                    if await request.is_disconnected():
                        return
                    yield fmt(ev)
                    if ev.get("event") in TERMINAL_EVENTS:
                        return
                if not active:
                    return
                while True:
                    try:
                        ev = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_SECONDS)
                    except asyncio.TimeoutError:
                        if await request.is_disconnected():
                            return
                        yield ": ping\n\n"
                        continue
                    if (ev.get("seq") or 0) <= last_seq:
                        continue
                    if await request.is_disconnected():
                        return
                    yield fmt(ev)
                    if ev.get("event") in TERMINAL_EVENTS:
                        return
                    last_seq = ev.get("seq") or 0
            finally:
                manager.unsubscribe(task_id, queue, kind=kind)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )