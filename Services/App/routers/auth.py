# -*- coding: utf-8 -*-
"""鉴权端点: 注册/登录/当前用户。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...audit_logs import client_ip, write_audit
from ..admin_settings import (
    get_non_admin_tabs,
    get_registration_enabled,
)
from ..db import get_db
from ..models import Role, User
from ..schemas import (
    ErrorCode,
    MeRead,
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
from ..security import JWT_EXPIRE_SECONDS

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register")
def register(req: RegisterRequest, request: Request, session: Session = Depends(get_db)):
    """注册新用户 (普通角色); 注册关闭时返回 403。"""
    if not get_registration_enabled(session):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": ErrorCode.FORBIDDEN, "message": "注册已关闭"},
        )
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
    visible_tabs = (
        get_non_admin_tabs(session)
        if user.role is None or user.role.code != "admin"
        else None
    )
    return ok(
        TokenResponse(
            access_token=token,
            token_type="bearer",
            expires_in=JWT_EXPIRE_SECONDS,
            user=UserRead.model_validate(user),
            visible_tabs=visible_tabs,
        )
    )


@router.get("/registration")
def registration_status(session: Session = Depends(get_db)):
    """公开: 注册是否开放 (前端隐藏/显示注册选项卡)。"""
    return ok({"enabled": get_registration_enabled(session)})


@router.get("/me")
def me(user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    """当前登录用户信息 + 非管理员可见选项卡。"""
    visible_tabs = (
        get_non_admin_tabs(session)
        if user.role is None or user.role.code != "admin"
        else None
    )
    return ok(MeRead(user=UserRead.model_validate(user), visible_tabs=visible_tabs or []))