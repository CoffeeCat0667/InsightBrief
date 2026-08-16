# -*- coding: utf-8 -*-
"""抓取任务契约: POST /api/crawl-tasks, GET /api/crawl-tasks(/{id}), POST .../{id}/cancel。

状态机: pending -> running -> completed | failed | cancelled。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


class TaskStatus(str, Enum):
    """任务通用状态机。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CrawlTaskCreate(BaseModel):
    """POST /api/crawl-tasks 请求体; source_ids 省略 = 全部启用源。"""

    source_ids: Optional[List[str]] = None


class CrawlRunRead(BaseModel):
    """抓取任务的逐源运行明细。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: str
    status: TaskStatus
    discovered_links: int = 0
    success_count: int = 0
    failed_count: int = 0
    error: Optional[Dict[str, Any]] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class CrawlTaskRead(BaseModel):
    """抓取任务响应 (runs 可选: 列表接口不带, 详情接口带)。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    status: TaskStatus
    progress: int
    stage: Optional[str] = None
    message: Optional[str] = None
    source_ids: Optional[List[str]] = None
    error: Optional[Dict[str, Any]] = None
    stats: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    runs: List[CrawlRunRead] = []


class TaskCancelRequest(BaseModel):
    """POST /api/crawl-tasks/{id}/cancel 请求体 (可选) 与响应。"""

    reason: Optional[str] = None


class TaskCancelRead(BaseModel):
    """取消操作响应: 返回目标任务最新状态。"""

    task_id: int
    task_status: TaskStatus
    requested: bool