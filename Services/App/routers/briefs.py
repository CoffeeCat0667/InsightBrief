# -*- coding: utf-8 -*-
"""简报端点: 创建/列表/详情/取消 + SSE 进度 + GET /api/briefs。

SSE 独立端点 GET /api/brief-tasks/{id}/events (与 crawl 的
/api/tasks/{id}/events 分开 — 两表 id 各自自增, 合并端点会歧义)。
简报任务允许并发 (决策 §15-4), 无 409 语义。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ...audit_logs import client_ip, write_audit
from ..models import Article, Brief, BriefItem, BriefTask, Source, User
from ..schemas import (
    ArticleCategory,
    BriefItemRead,
    BriefListParams,
    BriefRead,
    BriefTaskCreate,
    BriefTaskRead,
    Page,
    PageParams,
    TaskCancelRead,
    TaskCancelRequest,
    ok,
)
from ..schemas.task import TaskStatus
from ..security import get_current_user, require_admin
from ..task_manager import _TERMINAL, manager
from .tasks import _event_stream

router = APIRouter(prefix="/api/brief-tasks", tags=["brief-tasks"])
briefs_router = APIRouter(prefix="/api/briefs", tags=["briefs"])


@router.post("")
def create_brief_task(
    body: BriefTaskCreate,
    request: Request,
    session: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """创建简报生成任务 (对现有文章做 LLM 分类/摘要/综述, 人工触发)。"""
    if body.source_ids is not None:
        cleaned = [s for s in body.source_ids if s]
        if cleaned != body.source_ids:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "validation_error",
                    "message": "source_ids 含空字符串",
                },
            )
    task = BriefTask(
        user_id=user.id,
        status=TaskStatus.PENDING.value,
        params=body.model_dump(exclude_none=True),
    )
    session.add(task)
    session.flush()
    session.commit()
    task = session.get(BriefTask, task.id)
    from Report import brief_processor

    try:
        manager.dispatch(task.id, brief_processor, kind="brief")
    except Exception:
        write_audit(
            user_id=user.id,
            action="brief_task.create",
            target_type="brief_task",
            target_id=task.id,
            detail={**body.model_dump(exclude_none=True), "dispatch_failed": True},
            ip=client_ip(request),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "internal_error", "message": "任务执行器不可用"},
        )
    write_audit(
        user_id=user.id,
        action="brief_task.create",
        target_type="brief_task",
        target_id=task.id,
        detail=body.model_dump(exclude_none=True),
        ip=client_ip(request),
    )
    return ok(BriefTaskRead.model_validate(task))


@router.get("")
def list_brief_tasks(
    status: Optional[str] = None,
    page: PageParams = Depends(),
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """简报任务列表 (按创建时间倒序)。"""
    stmt = select(BriefTask)
    if status:
        stmt = stmt.where(BriefTask.status == status)
    total = (
        session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
        or 0
    )
    rows = session.scalars(
        stmt.order_by(BriefTask.id.desc())
        .offset((page.page - 1) * page.page_size)
        .limit(page.page_size)
    ).all()
    return ok(
        Page[BriefTaskRead](
            items=[BriefTaskRead.model_validate(r) for r in rows],
            total=total,
            page=page.page,
            page_size=page.page_size,
        )
    )


@router.get("/{task_id}")
def get_brief_task(
    task_id: int,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """简报任务详情。"""
    task = session.get(BriefTask, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"简报任务 {task_id} 不存在"},
        )
    return ok(BriefTaskRead.model_validate(task))


@router.post("/{task_id}/cancel")
def cancel_brief_task(
    task_id: int,
    request: Request,
    body: Optional[TaskCancelRequest] = None,
    session: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """请求取消简报任务 (admin, 阶段间生效)。"""
    task = session.get(BriefTask, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"简报任务 {task_id} 不存在"},
        )
    if task.status not in _TERMINAL and manager.request_cancel(task_id, kind="brief"):
        session.refresh(task)
        requested = True
    else:
        requested = False
    if requested:
        write_audit(
            user_id=user.id,
            action="brief_task.cancel",
            target_type="brief_task",
            target_id=task_id,
            detail={"requested": True, "task_status": task.status},
            ip=client_ip(request),
        )
    return ok(
        TaskCancelRead(task_id=task_id, task_status=task.status, requested=requested)
    )


@router.get("/{task_id}/events")
async def brief_task_event_stream(
    task_id: int,
    request: Request,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """brief 任务 SSE 进度通道 (与 crawl 端点分离, 消除 id 歧义)。"""
    task = session.get(BriefTask, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"简报任务 {task_id} 不存在"},
        )
    active = task.status not in _TERMINAL or manager.is_active(task_id, kind="brief")
    return StreamingResponse(
        _event_stream(task_id, "brief", active, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@briefs_router.get("")
def list_briefs(
    params: BriefListParams = Depends(),
    page: PageParams = Depends(),
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """简报列表 (可按任务/分类筛选; items 经子查询行数限制, 避免 N+1 全量)。"""
    stmt = select(Brief)
    if params.task_id:
        stmt = stmt.where(Brief.task_id == params.task_id)
    if params.category:
        stmt = stmt.where(Brief.category == params.category.value)
    total = (
        session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
        or 0
    )
    rows = session.scalars(
        stmt.order_by(Brief.id.desc())
        .offset((page.page - 1) * page.page_size)
        .limit(page.page_size)
    ).all()
    # 每份简报的条目 = 同一任务内 seq 排序直取 (行数可控, 无 N+1 隐患)
    items_by_brief: dict = {}
    if rows:
        item_rows = (
            session.execute(
                select(BriefItem)
                .where(BriefItem.brief_id.in_([r.id for r in rows]))
                .order_by(BriefItem.brief_id, BriefItem.seq)
            )
            .scalars()
            .all()
        )
        for it in item_rows:
            items_by_brief.setdefault(it.brief_id, []).append(it)
    data = []
    for r in rows:
        brief = BriefRead.model_validate(r)
        brief.items = [BriefItemRead.model_validate(i) for i in items_by_brief.get(r.id, [])]
        data.append(brief)
    return ok(
        Page[BriefRead](items=data, total=total, page=page.page, page_size=page.page_size)
    )


@briefs_router.get("/{brief_id}")
def get_brief(
    brief_id: int,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """单份简报详情 (含全部条目与原文 URL/源名)。"""
    brief = session.get(Brief, brief_id)
    if brief is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"简报 {brief_id} 不存在"},
        )
    items = (
        session.execute(
            select(BriefItem)
            .where(BriefItem.brief_id == brief_id)
            .order_by(BriefItem.seq)
        )
        .scalars()
        .all()
    )
    data = BriefRead.model_validate(brief)
    data.items = [BriefItemRead.model_validate(i) for i in items]
    return ok(data)