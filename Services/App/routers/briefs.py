# -*- coding: utf-8 -*-
"""简报端点: 创建/列表/详情/取消 + GET /api/briefs。

SSE 进度沿用 /api/tasks/{task_id}/events (同 event bus, TERMINAL_EVENTS
已含 brief_* 终态); 简报任务允许并发 (决策 §15-4), 无 409 语义。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
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

router = APIRouter(prefix="/api/brief-tasks", tags=["brief-tasks"])
briefs_router = APIRouter(prefix="/api/briefs", tags=["briefs"])


@router.post("")
def create_brief_task(
    body: BriefTaskCreate,
    session: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """创建简报生成任务 (对现有文章做 LLM 分类/摘要/综述, 人工触发)。"""
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

    manager.dispatch(task.id, brief_processor, kind="brief")
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
    body: Optional[TaskCancelRequest] = None,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """请求取消简报任务 (阶段间生效)。"""
    task = session.get(BriefTask, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"简报任务 {task_id} 不存在"},
        )
    if task.status not in _TERMINAL and manager.request_cancel(task_id, kind="brief"):
        session.refresh(task)
        return ok(
            TaskCancelRead(task_id=task_id, task_status=task.status, requested=True)
        )
    return ok(
        TaskCancelRead(task_id=task_id, task_status=task.status, requested=False)
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