# -*- coding: utf-8 -*-
"""抓取任务创建的共享业务服务，供 HTTP 路由和定时调度器复用。"""
from __future__ import annotations

from typing import Optional, Sequence

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CrawlTask, Source
from .schemas.task import CrawlTaskCreate, TaskStatus
from .task_manager import manager


class CrawlTaskConflictError(ValueError):
    """进行中任务与请求源集合重叠。"""


def _clean_source_ids(source_ids: Optional[Sequence[str]]) -> list[str]:
    if source_ids is None:
        return []
    ids = [source_id for source_id in source_ids if source_id]
    if ids != list(source_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "validation_error", "message": "source_ids 含空字符串"},
        )
    return ids


def validate_crawl_spec(
    session: Session,
    *,
    source_ids: Optional[Sequence[str]],
    domestic_max_ratio: int,
) -> list[str]:
    """校验抓取源存在/启用及国内源比例可行性，返回清理后的 source ids。"""
    ids = _clean_source_ids(source_ids)
    selected_sources = session.scalars(
        select(Source).where(Source.enabled.is_(True))
        if not ids
        else select(Source).where(Source.id.in_(ids), Source.enabled.is_(True))
    ).all()
    selected_by_id = {source.id: source for source in selected_sources}
    requested_ids = list(selected_by_id) if not ids else ids
    missing_ids = [source_id for source_id in requested_ids if source_id not in selected_by_id]
    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "validation_error",
                "message": f"源不存在或未启用: {missing_ids}",
            },
        )
    if domestic_max_ratio < 100 and requested_ids and all(
        selected_by_id[source_id].is_domestic for source_id in requested_ids
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "validation_error",
                "message": "国内源占比限制小于 100% 时, 至少选择一个外源",
            },
        )
    return ids


def find_conflicting_task(session: Session, source_ids: Sequence[str]) -> Optional[CrawlTask]:
    """返回与源集合冲突的进行中抓取任务。空集合代表全部启用源。"""
    for task in session.scalars(
        select(CrawlTask).where(
            CrawlTask.status.in_([TaskStatus.PENDING.value, TaskStatus.RUNNING.value])
        )
    ).all():
        if not task.source_ids or not source_ids or set(task.source_ids) & set(source_ids):
            return task
    return None


def create_crawl_task(
    session: Session,
    body: CrawlTaskCreate,
    *,
    user_id: int,
    schedule_id: Optional[int] = None,
    generate_brief: bool = False,
    dispatch: bool = True,
) -> CrawlTask:
    """校验、持久化并可选派发真实抓取任务。"""
    ids = validate_crawl_spec(
        session,
        source_ids=body.source_ids,
        domestic_max_ratio=body.domestic_max_ratio,
    )
    conflict = find_conflicting_task(session, ids)
    if conflict is not None:
        raise CrawlTaskConflictError(str(conflict.id))
    task = CrawlTask(
        user_id=user_id,
        status=TaskStatus.PENDING.value,
        source_ids=body.source_ids,
        max_items=body.max_items,
        domestic_max_ratio=body.domestic_max_ratio,
        schedule_id=schedule_id,
        generate_brief=generate_brief or body.generate_brief,
    )
    session.add(task)
    session.flush()
    session.commit()
    session.refresh(task)
    if not dispatch:
        return task
    try:
        manager.dispatch(task.id, kind="crawl")
    except RuntimeError:
        raise
    return task
