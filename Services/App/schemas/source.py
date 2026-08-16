# -*- coding: utf-8 -*-
"""源管理契约: GET/POST /api/sources, PATCH/DELETE /api/sources/{id}。

kind = rss | column | custom; config 按 kind 携带发现参数
(rss: feeds/url_replace/skip_substrings; column: column_url/link_pattern; custom: 空)。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class SourceKind(str, Enum):
    RSS = "rss"
    COLUMN = "column"
    CUSTOM = "custom"


class SourceCreate(BaseModel):
    """POST /api/sources 请求体。"""

    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=1, max_length=255)
    kind: SourceKind
    platform_ids: List[str] = Field(default_factory=list)
    is_domestic: bool = False
    config: Dict[str, Any] = Field(default_factory=dict)
    description: Optional[str] = None


class SourceUpdate(BaseModel):
    """PATCH /api/sources/{id} 请求体 (全字段可选)。"""

    name: Optional[str] = Field(default=None, max_length=255)
    kind: Optional[SourceKind] = None
    platform_ids: Optional[List[str]] = None
    is_domestic: Optional[bool] = None
    enabled: Optional[bool] = None
    config: Optional[Dict[str, Any]] = None
    description: Optional[str] = None


class SourceRead(BaseModel):
    """源响应模型 (来源: sources 表, DB 为唯一真相源)。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    kind: SourceKind
    platform_ids: List[str]
    is_domestic: bool
    enabled: bool
    config: Dict[str, Any]
    description: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None