# -*- coding: utf-8 -*-
"""定时抓取计划 CRUD / 启停 / 立即执行端点。"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...audit_logs import client_ip, write_audit
from ..crawl_service import validate_crawl_spec
from ..db import get_db
from ..models import CrawlSchedule, User
from ..schedule_manager import schedule_manager
from ..schemas import (
    CrawlScheduleCreate,
    CrawlScheduleRead,
    CrawlScheduleUpdate,
    Page,
    PageParams,
    ok,
)
from ..security import require_admin

router = APIRouter(prefix="/api/crawl-schedules", tags=["crawl-schedules"])


def _validate_spec(
    session: Session,
    *,
    source_ids: list[str] | None,
    domestic_max_ratio: int,
) -> None:
    validate_crawl_spec(
        session,
        source_ids=source_ids,
        domestic_max_ratio=domestic_max_ratio,
    )


@router.get("")
def list_crawl_schedules(
    page: PageParams = Depends(),
    session: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    stmt = select(CrawlSchedule)
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = session.scalars(
        stmt.order_by(CrawlSchedule.id.desc())
        .offset((page.page - 1) * page.page_size)
        .limit(page.page_size)
    ).all()
    return ok(
        Page[CrawlScheduleRead](
            items=[CrawlScheduleRead.model_validate(row) for row in rows],
            total=total,
            page=page.page,
            page_size=page.page_size,
        )
    )


@router.post("")
def create_crawl_schedule(
    body: CrawlScheduleCreate,
    request: Request,
    session: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    _validate_spec(
        session,
        source_ids=body.source_ids,
        domestic_max_ratio=body.domestic_max_ratio,
    )
    now = datetime.now(timezone.utc)
    schedule = CrawlSchedule(
        user_id=user.id,
        enabled=body.enabled,
        interval_hours=body.interval_hours,
        max_runs=body.max_runs,
        source_ids=body.source_ids,
        max_items=body.max_items,
        domestic_max_ratio=body.domestic_max_ratio,
        generate_brief=body.generate_brief,
        next_run_at=now,
    )
    session.add(schedule)
    session.commit()
    session.refresh(schedule)
    write_audit(
        user_id=user.id,
        action="crawl_schedule.create",
        target_type="crawl_schedule",
        target_id=schedule.id,
        detail=body.model_dump(),
        ip=client_ip(request),
    )
    return ok(CrawlScheduleRead.model_validate(schedule))


@router.patch("/{schedule_id}")
def update_crawl_schedule(
    schedule_id: int,
    body: CrawlScheduleUpdate,
    request: Request,
    session: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    schedule = session.get(CrawlSchedule, schedule_id)
    if schedule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"定时任务 {schedule_id} 不存在"},
        )
    changes = body.model_dump(exclude_unset=True)
    source_ids = changes.get("source_ids", schedule.source_ids)
    ratio = changes.get("domestic_max_ratio", schedule.domestic_max_ratio)
    _validate_spec(
        session,
        source_ids=source_ids,
        domestic_max_ratio=ratio,
    )
    was_enabled = schedule.enabled
    for key, value in changes.items():
        setattr(schedule, key, value)
    if changes.get("enabled") is True and not was_enabled:
        schedule.next_run_at = datetime.now(timezone.utc)
        schedule.last_error = None
    session.commit()
    session.refresh(schedule)
    write_audit(
        user_id=user.id,
        action="crawl_schedule.update",
        target_type="crawl_schedule",
        target_id=schedule.id,
        detail=changes,
        ip=client_ip(request),
    )
    return ok(CrawlScheduleRead.model_validate(schedule))


@router.post("/{schedule_id}/enable")
def enable_crawl_schedule(
    schedule_id: int,
    request: Request,
    session: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    schedule = session.get(CrawlSchedule, schedule_id)
    if schedule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"定时任务 {schedule_id} 不存在"},
        )
    if schedule.max_runs and schedule.run_count >= schedule.max_runs:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "conflict", "message": "已达到最多执行次数，请提高上限后再启用"},
        )
    schedule.enabled = True
    schedule.next_run_at = datetime.now(timezone.utc)
    schedule.last_error = None
    session.commit()
    write_audit(
        user_id=user.id,
        action="crawl_schedule.enable",
        target_type="crawl_schedule",
        target_id=schedule.id,
        detail={},
        ip=client_ip(request),
    )
    return ok(CrawlScheduleRead.model_validate(schedule))


@router.post("/{schedule_id}/disable")
def disable_crawl_schedule(
    schedule_id: int,
    request: Request,
    session: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    schedule = session.get(CrawlSchedule, schedule_id)
    if schedule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"定时任务 {schedule_id} 不存在"},
        )
    schedule.enabled = False
    session.commit()
    write_audit(
        user_id=user.id,
        action="crawl_schedule.disable",
        target_type="crawl_schedule",
        target_id=schedule.id,
        detail={},
        ip=client_ip(request),
    )
    return ok(CrawlScheduleRead.model_validate(schedule))


@router.post("/{schedule_id}/run-now")
def run_crawl_schedule_now(
    schedule_id: int,
    request: Request,
    session: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    if session.get(CrawlSchedule, schedule_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"定时任务 {schedule_id} 不存在"},
        )
    try:
        task = schedule_manager.run_now(schedule_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "conflict", "message": str(exc)},
        )
    write_audit(
        user_id=user.id,
        action="crawl_schedule.run_now",
        target_type="crawl_schedule",
        target_id=schedule_id,
        detail={"crawl_task_id": task.id},
        ip=client_ip(request),
    )
    return ok({"schedule_id": schedule_id, "crawl_task_id": task.id})


@router.delete("/{schedule_id}")
def delete_crawl_schedule(
    schedule_id: int,
    request: Request,
    session: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    schedule = session.get(CrawlSchedule, schedule_id)
    if schedule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"定时任务 {schedule_id} 不存在"},
        )
    session.delete(schedule)
    session.commit()
    write_audit(
        user_id=user.id,
        action="crawl_schedule.delete",
        target_type="crawl_schedule",
        target_id=schedule_id,
        detail={},
        ip=client_ip(request),
    )
    return ok({"deleted": schedule_id})
