# -*- coding: utf-8 -*-
"""简报契约: POST /api/brief-tasks, GET /api/brief-tasks/{id}, GET /api/briefs(/{id})。"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .article import ArticleCategory
from .task import TaskStatus


class BriefTaskCreate(BaseModel):
    """POST /api/brief-tasks 请求体: 限定时间范围/源/分类生成简报。"""

    category: Optional[ArticleCategory] = None  # 缺省 = 全部分类
    source_ids: Optional[List[str]] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    max_items: Optional[int] = Field(default=None, ge=1, le=500)  # 文章上限 (最新优先)


class BriefTaskRead(BaseModel):
    """简报生成任务状态。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    status: TaskStatus
    progress: int
    stage: Optional[str] = None
    message: Optional[str] = None
    params: Optional[dict] = None
    error: Optional[dict] = None
    stats: Optional[dict] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class BriefItemRead(BaseModel):
    """简报条目 (meta 携带单篇降级标记: {degraded: type})。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    article_id: int
    seq: int
    title_cn: Optional[str] = None
    summary: Optional[str] = None
    category: Optional[ArticleCategory] = None
    source_name: Optional[str] = None
    url: str
    meta: Optional[dict] = None


class BriefRead(BaseModel):
    """一份简报 (含条目)。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    category: Optional[ArticleCategory] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    stats: Optional[dict] = None
    generated_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    items: List[BriefItemRead] = []


class BriefListParams(BaseModel):
    """GET /api/briefs 筛选参数。"""

    task_id: Optional[int] = None
    category: Optional[ArticleCategory] = None