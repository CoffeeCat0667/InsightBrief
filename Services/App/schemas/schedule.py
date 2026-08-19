# -*- coding: utf-8 -*-
"""定时抓取计划 API 契约。"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class CrawlScheduleCreate(BaseModel):
    source_ids: Optional[List[str]] = None
    max_items: int = Field(default=30, ge=1, le=500)
    domestic_max_ratio: int = Field(default=100, ge=0, le=100)
    interval_hours: int = Field(ge=1, le=720)
    max_runs: int = Field(default=0, ge=0, le=100000)
    generate_brief: bool = False
    enabled: bool = True


class CrawlScheduleUpdate(BaseModel):
    source_ids: Optional[List[str]] = None
    max_items: Optional[int] = Field(default=None, ge=1, le=500)
    domestic_max_ratio: Optional[int] = Field(default=None, ge=0, le=100)
    interval_hours: Optional[int] = Field(default=None, ge=1, le=720)
    max_runs: Optional[int] = Field(default=None, ge=0, le=100000)
    generate_brief: Optional[bool] = None
    enabled: Optional[bool] = None


class CrawlScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    enabled: bool
    interval_hours: int
    max_runs: int
    run_count: int
    source_ids: Optional[List[str]] = None
    max_items: int
    domestic_max_ratio: int
    generate_brief: bool
    next_run_at: datetime
    last_run_at: Optional[datetime] = None
    last_task_id: Optional[int] = None
    last_brief_task_id: Optional[int] = None
    last_error: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
