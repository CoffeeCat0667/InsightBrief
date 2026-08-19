# -*- coding: utf-8 -*-
"""持久化定时抓取计划及本次抓取文章关联。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class CrawlSchedule(TimestampMixin, Base):
    """按小时循环创建抓取任务的持久化模板。"""

    __tablename__ = "crawl_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    interval_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    max_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    source_ids: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    max_items: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    domestic_max_ratio: Mapped[int] = mapped_column(Integer, nullable=False, default=100, server_default="100")
    generate_brief: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # IDs are informational pointers; keeping them non-FK avoids a cyclic
    # dependency between the schedule and task tables during bootstrap.
    last_task_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_brief_task_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class CrawlTaskArticle(Base):
    """抓取任务实际处理的文章，用于精确生成自动简报。"""

    __tablename__ = "crawl_task_articles"
    __table_args__ = (
        UniqueConstraint("crawl_task_id", "article_id", name="uq_crawl_task_articles_task_article"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    crawl_task_id: Mapped[int] = mapped_column(
        ForeignKey("crawl_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
