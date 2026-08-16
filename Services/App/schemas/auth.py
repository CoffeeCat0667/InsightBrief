# -*- coding: utf-8 -*-
"""鉴权契约 (契约先行, 路由与实现归鉴权步骤)。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    """注册请求。"""

    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_]+$")
    password: str = Field(min_length=8, max_length=128)
    email: Optional[EmailStr] = None


class LoginRequest(BaseModel):
    """登录请求。"""

    username: str
    password: str


class RoleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: Optional[str] = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: Optional[str] = None
    role: Optional[RoleRead] = None
    is_active: bool
    created_at: Optional[datetime] = None


class TokenResponse(BaseModel):
    """登录/注册成功响应 (Bearer Token 后续端点经 Authorization 头携带)。"""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = 86400
    user: UserRead