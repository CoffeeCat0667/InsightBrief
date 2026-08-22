# -*- coding: utf-8 -*-
"""管理面板契约。"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class UserAdminRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: Optional[str] = None
    role_code: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime] = None


class UserAdminCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_]+$")
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(pattern=r"^(admin|user)$")
    email: Optional[str] = None

    def model_post_init(self, __context) -> None:
        if len(self.password.encode("utf-8")) > 72:
            raise ValueError("密码不能超过 72 个 UTF-8 字节")


class UserAdminUpdate(BaseModel):
    username: Optional[str] = Field(default=None, min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_]+$")
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)
    role: Optional[str] = Field(default=None, pattern=r"^(admin|user)$")

    def model_post_init(self, __context) -> None:
        if self.password is not None and len(self.password.encode("utf-8")) > 72:
            raise ValueError("密码不能超过 72 个 UTF-8 字节")


class RegistrationUpdate(BaseModel):
    enabled: bool


class LLMSettingsUpdate(BaseModel):
    base_url: str = Field(min_length=1)
    api_key: str = Field(min_length=1)
    model_id: str = Field(min_length=1)


class TabsUpdate(BaseModel):
    tabs: List[str] = Field(min_length=1)


class LoggingSettingsUpdate(BaseModel):
    """PUT /api/admin/logging 请求体。"""
    level: str = Field(min_length=1)
    max_file_size_mb: int = Field(ge=1, le=100)


class LoggingSettingsRead(BaseModel):
    """GET /api/admin/logging 响应体。"""
    level: str
    max_file_size_mb: int
    log_file_path: str
