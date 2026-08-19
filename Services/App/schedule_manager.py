# -*- coding: utf-8 -*-
"""定时抓取调度器：数据库持久化计划 + 轻量后台线程。"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select

from .crawl_service import CrawlTaskConflictError, create_crawl_task
from .db import SessionLocal
from .models import CrawlSchedule, CrawlTask
from .schemas import CrawlTaskCreate
from .schemas.task import TaskStatus

logger = logging.getLogger(__name__)


class ScheduleManager:
    """轮询到期计划，创建真实 crawl task；业务执行仍交给 TaskManager。"""

    def __init__(self, poll_seconds: float = 15.0) -> None:
        self._poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="crawl-scheduler", daemon=True
        )
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._poll_seconds + 2)
        self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self._poll_seconds):
            try:
                self.run_due()
            except Exception:
                logger.exception("定时抓取调度循环异常")

    @staticmethod
    def _task_body(schedule: CrawlSchedule) -> CrawlTaskCreate:
        return CrawlTaskCreate(
            source_ids=schedule.source_ids,
            max_items=schedule.max_items,
            domestic_max_ratio=schedule.domestic_max_ratio,
            generate_brief=schedule.generate_brief,
        )

    @staticmethod
    def _next_time(now: datetime, interval_hours: int) -> datetime:
        return now + timedelta(hours=interval_hours)

    def run_due(self) -> int:
        """执行当前到期计划；单次扫描每条计划最多触发一次。"""
        now = datetime.now(timezone.utc)
        dispatched = 0
        with SessionLocal() as session:
            schedules = session.scalars(
                select(CrawlSchedule)
                .where(
                    CrawlSchedule.enabled.is_(True),
                    CrawlSchedule.next_run_at <= now,
                )
                .order_by(CrawlSchedule.next_run_at, CrawlSchedule.id)
                .with_for_update(skip_locked=True)
            ).all()
            for schedule in schedules:
                if schedule.max_runs and schedule.run_count >= schedule.max_runs:
                    schedule.enabled = False
                    schedule.last_error = "已达到最多执行次数"
                    session.commit()
                    continue
                body = self._task_body(schedule)
                active_from_schedule = session.scalar(
                    select(CrawlTask.id).where(
                        CrawlTask.schedule_id == schedule.id,
                        CrawlTask.status.in_(
                            [TaskStatus.PENDING.value, TaskStatus.RUNNING.value]
                        ),
                    )
                )
                if active_from_schedule is not None:
                    schedule.last_error = "本轮跳过：上一轮计划抓取尚未结束"
                    schedule.next_run_at = self._next_time(now, schedule.interval_hours)
                    session.commit()
                    continue
                try:
                    task = create_crawl_task(
                        session,
                        body,
                        user_id=schedule.user_id,
                        schedule_id=schedule.id,
                        generate_brief=schedule.generate_brief,
                    )
                except CrawlTaskConflictError:
                    schedule.last_error = "本轮跳过：源集合与进行中抓取任务冲突"
                    schedule.next_run_at = self._next_time(now, schedule.interval_hours)
                    session.commit()
                    continue
                except HTTPException as exc:
                    schedule.last_error = str(exc.detail.get("message", "计划配置无效"))
                    schedule.next_run_at = self._next_time(now, schedule.interval_hours)
                    session.commit()
                    continue
                except RuntimeError:
                    schedule.last_error = "任务执行器不可用"
                    schedule.next_run_at = self._next_time(now, schedule.interval_hours)
                    session.commit()
                    continue
                schedule.run_count += 1
                schedule.last_run_at = now
                schedule.last_task_id = task.id
                schedule.last_error = None
                schedule.next_run_at = self._next_time(now, schedule.interval_hours)
                if schedule.max_runs and schedule.run_count >= schedule.max_runs:
                    schedule.enabled = False
                session.commit()
                dispatched += 1
        return dispatched

    def run_now(self, schedule_id: int) -> CrawlTask:
        """管理员主动立即执行，不改变原有周期的 next_run_at。"""
        with SessionLocal() as session:
            schedule = session.get(CrawlSchedule, schedule_id)
            if schedule is None:
                raise KeyError(schedule_id)
            if schedule.max_runs and schedule.run_count >= schedule.max_runs:
                schedule.enabled = False
                schedule.last_error = "已达到最多执行次数"
                session.commit()
                raise ValueError("已达到最多执行次数")
            try:
                task = create_crawl_task(
                    session,
                    self._task_body(schedule),
                    user_id=schedule.user_id,
                    schedule_id=schedule.id,
                    generate_brief=schedule.generate_brief,
                )
            except CrawlTaskConflictError:
                raise ValueError("源集合与进行中抓取任务冲突")
            schedule.run_count += 1
            schedule.last_run_at = datetime.now(timezone.utc)
            schedule.last_task_id = task.id
            schedule.last_error = None
            if schedule.max_runs and schedule.run_count >= schedule.max_runs:
                schedule.enabled = False
            session.commit()
            return task


schedule_manager = ScheduleManager()
