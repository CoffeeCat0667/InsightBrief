# -*- coding: utf-8 -*-
"""鉴权端点: 注册/登录/当前用户。"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Role, User
from ..schemas import (
    ErrorCode,
    RegisterRequest,
    TokenResponse,
    UserRead,
    ok,
)
from ..security import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register")
def register(req: RegisterRequest, session: Session = Depends(get_db)):
    """注册新用户 (普通角色); 用户名/邮箱冲突返回 409。"""
    if session.scalar(select(User).where(User.username == req.username)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": ErrorCode.CONFLICT, "message": "用户名已存在"},
        )
    if req.email and session.scalar(select(User).where(User.email == req.email)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": ErrorCode.CONFLICT, "message": "邮箱已被注册"},
        )
    user_role = session.scalar(select(Role).where(Role.code == "user"))
    user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        email=req.email,
        role_id=user_role.id if user_role else None,
        is_active=True,
    )
    session.add(user)
    session.commit()
    return ok(UserRead.model_validate(user))


@router.post("/login")
def login(form: OAuth2PasswordRequestForm = Depends(), session: Session = Depends(get_db)):
    """OAuth2 表单登录 -> Bearer Token (OpenAPI 授权按钮可直接用)。"""
    user = session.scalar(select(User).where(User.username == form.username))
    if user is None or not verify_password(form.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": ErrorCode.UNAUTHORIZED, "message": "用户名或密码错误"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": ErrorCode.FORBIDDEN, "message": "账号已被禁用"},
        )
    token = create_access_token(user.id)
    return ok(
        TokenResponse(
            access_token=token,
            token_type="bearer",
            expires_in=int(os.environ.get("JWT_EXPIRE_SECONDS", "86400")),
            user=UserRead.model_validate(user),
        )
    )


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    """当前登录用户信息。"""
    return ok(UserRead.model_validate(user))