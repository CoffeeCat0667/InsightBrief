# -*- coding: utf-8 -*-
"""鉴权端点: 注册/登录/当前用户。"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...audit_logs import client_ip, write_audit
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
    verify_dummy_password,
    verify_password,
)
from ..login_rate_limit import login_rate_limiter

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register")
def register(req: RegisterRequest, request: Request, session: Session = Depends(get_db)):
    """注册新用户 (普通角色); 用户名/邮箱冲突返回 409。"""
    if session.scalar(select(User).where(User.username == req.username)) is not None:
        write_audit(
            action="user.register_failed",
            target_type="user",
            detail={"reason": "用户名已存在"},
            ip=client_ip(request),
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": ErrorCode.CONFLICT, "message": "用户名已存在"},
        )
    if req.email and session.scalar(select(User).where(User.email == req.email)) is not None:
        write_audit(
            action="user.register_failed",
            target_type="user",
            detail={"reason": "邮箱已被注册"},
            ip=client_ip(request),
        )
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
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        write_audit(
            action="user.register_failed",
            target_type="user",
            detail={"reason": "用户名或邮箱已被注册"},
            ip=client_ip(request),
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": ErrorCode.CONFLICT, "message": "用户名或邮箱已被注册"},
        )
    write_audit(
        user_id=user.id,
        action="user.register",
        target_type="user",
        target_id=user.id,
        detail={},
        ip=client_ip(request),
    )
    return ok(UserRead.model_validate(user))


@router.post("/login")
def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_db),
):
    """OAuth2 表单登录 -> Bearer Token (OpenAPI 授权按钮可直接用)。"""
    ip = client_ip(request) or "unknown"
    retry_after = login_rate_limiter.is_limited(ip)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(retry_after)},
            detail={"code": ErrorCode.RATE_LIMITED, "message": "登录失败次数过多, 请稍后再试"},
        )
    user = session.scalar(select(User).where(User.username == form.username))
    if user is None:
        verify_dummy_password(form.password)
        valid = False
    else:
        valid = verify_password(form.password, user.password_hash)
    if not valid:
        limited, retry_after = login_rate_limiter.record_failure(ip)
        write_audit(
            action="user.login_failed",
            target_type="user",
            detail={"reason": "用户名或密码错误"},
            ip=ip,
        )
        if limited:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={"Retry-After": str(retry_after or 1)},
                detail={"code": ErrorCode.RATE_LIMITED, "message": "登录失败次数过多, 请稍后再试"},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": ErrorCode.UNAUTHORIZED, "message": "用户名或密码错误"},
        )
    if not user.is_active:
        limited, retry_after = login_rate_limiter.record_failure(ip)
        write_audit(
            user_id=user.id,
            action="user.login_failed",
            target_type="user",
            target_id=user.id,
            detail={"reason": "账号已被禁用"},
            ip=ip,
        )
        if limited:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={"Retry-After": str(retry_after or 1)},
                detail={"code": ErrorCode.RATE_LIMITED, "message": "登录失败次数过多, 请稍后再试"},
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": ErrorCode.FORBIDDEN, "message": "账号已被禁用"},
        )
    login_rate_limiter.reset(ip)
    token = create_access_token(user.id)
    write_audit(
        user_id=user.id,
        action="user.login",
        target_type="user",
        target_id=user.id,
        detail={},
        ip=ip,
    )
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