# -*- coding: utf-8 -*-
"""抓取完成后的精确范围自动简报触发。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from .db import SessionLocal
from .models import BriefTask, CrawlSchedule, CrawlTask, CrawlTaskArticle
from .schemas.task import TaskStatus
from .task_manager import manager

logger = logging.getLogger(__name__)


class AutoBriefManager:
    """为满足条件的 crawl task 创建唯一的 brief task。"""

    def create_for_crawl(self, crawl_task_id: int) -> int | None:
        from Report import brief_processor

        with SessionLocal() as session:
            crawl_task = session.get(CrawlTask, crawl_task_id)
            if (
                crawl_task is None
                or not crawl_task.generate_brief
                or crawl_task.status != TaskStatus.COMPLETED.value
            ):
                return None
            article_ids = list(
                session.scalars(
                    select(CrawlTaskArticle.article_id).where(
                        CrawlTaskArticle.crawl_task_id == crawl_task_id,
                        CrawlTaskArticle.outcome == "inserted",
                    )
                ).all()
            )
            if not article_ids:
                crawl_task.message = "抓取完成：没有新增文章，跳过自动简报"
                if crawl_task.schedule_id is not None:
                    schedule = session.get(CrawlSchedule, crawl_task.schedule_id)
                    if schedule is not None:
                        schedule.last_error = "本次没有新增文章，跳过自动简报"
                session.commit()
                return None
            existing = session.scalar(
                select(BriefTask).where(
                    BriefTask.origin_crawl_task_id == crawl_task_id
                )
            )
            if existing is not None:
                return existing.id
            task = BriefTask(
                user_id=crawl_task.user_id,
                origin_crawl_task_id=crawl_task_id,
                status=TaskStatus.PENDING.value,
                params={"article_ids": article_ids, "source_ids": crawl_task.source_ids},
            )
            session.add(task)
            try:
                session.flush()
                session.commit()
            except Exception:
                session.rollback()
                existing = session.scalar(
                    select(BriefTask).where(
                        BriefTask.origin_crawl_task_id == crawl_task_id
                    )
                )
                if existing is not None:
                    return existing.id
                raise
            task_id = task.id
        try:
            manager.dispatch(task_id, brief_processor, kind="brief")
        except RuntimeError:
            with SessionLocal() as session:
                failed = session.get(BriefTask, task_id)
                if failed is not None:
                    failed.status = TaskStatus.FAILED.value
                    failed.progress = 100
                    failed.error = {"code": "internal_error", "message": "自动简报执行器不可用"}
                    failed.finished_at = datetime.now(timezone.utc)
                    session.commit()
            raise
        with SessionLocal() as session:
            crawl_task = session.get(CrawlTask, crawl_task_id)
            if crawl_task is not None:
                crawl_task.message = f"已创建自动简报任务 #{task_id}"
                if crawl_task.schedule_id is not None:
                    schedule = session.get(CrawlSchedule, crawl_task.schedule_id)
                    if schedule is not None:
                        schedule.last_brief_task_id = task_id
                        schedule.last_error = None
                session.commit()
        return task_id


    def recover(self) -> int:
        """启动补偿：恢复服务中断时尚未创建的自动简报。"""
        with SessionLocal() as session:
            ids = list(
                session.scalars(
                    select(CrawlTask.id).where(
                        CrawlTask.status == TaskStatus.COMPLETED.value,
                        CrawlTask.generate_brief.is_(True),
                    )
                ).all()
            )
        created = 0
        for crawl_id in ids:
            with SessionLocal() as session:
                exists = session.scalar(
                    select(BriefTask.id).where(
                        BriefTask.origin_crawl_task_id == crawl_id
                    )
                )
            if exists is None and self.create_for_crawl(crawl_id):
                created += 1
        return created


auto_brief_manager = AutoBriefManager()
