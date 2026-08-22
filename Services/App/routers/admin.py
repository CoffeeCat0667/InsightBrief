# -*- coding: utf-8 -*-
"""管理面板端点: 用户 / 注册开关 / LLM 配置 / 非管理员选项卡 (全部 admin-only)。"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...audit_logs import client_ip, write_audit
from ..admin_settings import (
    LLMProbeError,
    current_llm_fields,
    get_logging_config,
    get_non_admin_tabs,
    get_registration_enabled,
    probe_llm,
    set_logging_config,
    set_non_admin_tabs,
    set_registration_enabled,
    write_llm_fields,
)
from ..db import get_db
from ..models import CrawlTask, Role, User
from ..logging_config import reconfigure_logging
from ..schemas import (
    LLMSettingsUpdate,
    LoggingSettingsUpdate,
    RegistrationUpdate,
    TabsUpdate,
    UserAdminCreate,
    UserAdminRead,
    UserAdminUpdate,
    ok,
)
from ..schemas.auth import UserRead
from ..security import get_current_user, hash_password, require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users")
def list_admin_users(
    session: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    users = session.scalars(select(User).order_by(User.id)).all()
    items = []
    for user in users:
        role_code = user.role.code if user.role is not None else None
        items.append(
            UserAdminRead(
                id=user.id,
                username=user.username,
                email=user.email,
                role_code=role_code,
                is_active=user.is_active,
                created_at=user.created_at,
            ).model_dump()
        )
    return ok(items)


@router.post("/users")
def create_admin_user(
    body: UserAdminCreate,
    request: Request,
    session: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    existing = session.scalar(select(User).where(User.username == body.username))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "conflict", "message": "用户名已被使用"},
        )
    if body.email:
        existing_email = session.scalar(select(User).where(User.email == body.email))
        if existing_email is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "conflict", "message": "邮箱已被使用"},
            )
    role = session.scalar(select(Role).where(Role.code == body.role))
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "validation_error", "message": "角色不存在"},
        )
    target = User(
        username=body.username,
        password_hash=hash_password(body.password),
        email=body.email,
        role_id=role.id,
        is_active=True,
    )
    session.add(target)
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "conflict", "message": "用户名或邮箱已被使用"},
        )
    session.refresh(target)
    write_audit(
        user_id=user.id,
        action="user.create",
        target_type="user",
        target_id=target.id,
        detail={"username": target.username, "role": body.role},
        ip=client_ip(request),
    )
    return ok(
        UserAdminRead(
            id=target.id,
            username=target.username,
            email=target.email,
            role_code=body.role,
            is_active=True,
            created_at=target.created_at,
        ).model_dump()
    )


@router.patch("/users/{user_id}")
def update_admin_user(
    user_id: int,
    body: UserAdminUpdate,
    request: Request,
    session: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    target = session.get(User, user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"用户 {user_id} 不存在"},
        )
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "validation_error", "message": "未提供要修改的字段"},
        )
    if "username" in changes and changes["username"] != target.username:
        existing = session.scalar(
            select(User).where(User.username == changes["username"])
        )
        if existing is not None and existing.id != target.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "conflict", "message": "用户名已被使用"},
            )
        target.username = changes["username"]
    if "password" in changes and changes["password"]:
        target.password_hash = hash_password(changes["password"])
    if "role" in changes and changes["role"] != (target.role.code if target.role else None):
        new_role = session.scalar(select(Role).where(Role.code == changes["role"]))
        if new_role is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "validation_error", "message": "角色不存在"},
            )
        if target.id == user.id and target.role is not None and target.role.code == "admin":
            admin_count = session.scalar(
                select(func.count()).select_from(User).where(User.role_id.in_(
                    select(Role.id).where(Role.code == "admin")
                ))
            ) or 0
            if changes["role"] != "admin" and admin_count <= 1:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "conflict", "message": "不能移除最后一个管理员"},
                )
        target.role_id = new_role.id
    session.commit()
    session.refresh(target)
    detail = {key: (value if key != "password" else "***") for key, value in changes.items()}
    write_audit(
        user_id=user.id,
        action="user.update",
        target_type="user",
        target_id=target.id,
        detail=detail,
        ip=client_ip(request),
    )
    return ok(UserRead.model_validate(target))


@router.delete("/users/{user_id}")
def delete_admin_user(
    user_id: int,
    request: Request,
    session: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    target = session.get(User, user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"用户 {user_id} 不存在"},
        )
    if target.id == user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "conflict", "message": "不能删除当前登录用户"},
        )
    is_admin = target.role is not None and target.role.code == "admin"
    if is_admin:
        admin_count = session.scalar(
            select(func.count()).select_from(User).where(User.role_id.in_(
                select(Role.id).where(Role.code == "admin")
            ))
        ) or 0
        if admin_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "conflict", "message": "不能删除最后一个管理员"},
            )
    has_references = (
        session.scalar(
            select(func.count())
            .select_from(User)
            .join(CrawlTask, CrawlTask.user_id == User.id)
            .where(User.id == target.id)
        )
        or 0
    ) > 0
    if has_references:
        target.is_active = False
        session.commit()
        write_audit(
            user_id=user.id,
            action="user.disable",
            target_type="user",
            target_id=target.id,
            detail={"username": target.username, "reason": "存在业务数据, 软禁用"},
            ip=client_ip(request),
        )
        return ok({"deleted": None, "disabled": True, "user_id": target.id})
    session.delete(target)
    session.commit()
    write_audit(
        user_id=user.id,
        action="user.delete",
        target_type="user",
        target_id=target.id,
        detail={"username": target.username},
        ip=client_ip(request),
    )
    return ok({"deleted": True, "user_id": target.id})


@router.get("/registration")
def read_registration(
    session: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    return ok({"enabled": get_registration_enabled(session)})


@router.put("/registration")
def update_registration(
    body: RegistrationUpdate,
    request: Request,
    session: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    set_registration_enabled(session, body.enabled)
    write_audit(
        user_id=user.id,
        action="registration.set",
        target_type="system",
        detail={"enabled": body.enabled},
        ip=client_ip(request),
    )
    return ok({"enabled": body.enabled})


@router.get("/llm")
def read_llm_settings(
    _: User = Depends(require_admin),
):
    return ok(current_llm_fields())


@router.put("/llm")
def update_llm_settings(
    body: LLMSettingsUpdate,
    request: Request,
    session: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    try:
        probe_llm(body.base_url, body.api_key, body.model_id)
    except LLMProbeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "upstream_error", "message": f"LLM 连通性检查失败: {exc}"},
        )
    updated = write_llm_fields(
        session,
        base_url=body.base_url,
        api_key=body.api_key,
        model_id=body.model_id,
    )
    write_audit(
        user_id=user.id,
        action="llm.update",
        target_type="system",
        detail={"base_url": updated["base_url"], "model_id": updated["model_id"]},
        ip=client_ip(request),
    )
    return ok(updated)


@router.get("/tabs")
def read_non_admin_tabs(
    session: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    return ok({"tabs": get_non_admin_tabs(session)})


@router.put("/tabs")
def update_non_admin_tabs(
    body: TabsUpdate,
    request: Request,
    session: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    cleaned = set_non_admin_tabs(session, body.tabs)
    write_audit(
        user_id=user.id,
        action="tabs.update",
        target_type="system",
        detail={"tabs": cleaned},
        ip=client_ip(request),
    )
    return ok({"tabs": cleaned})


@router.get("/logging")
def read_logging_settings(
    session: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    return ok(get_logging_config(session))


@router.put("/logging")
def update_logging_settings(
    body: LoggingSettingsUpdate,
    request: Request,
    session: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    try:
        cfg = set_logging_config(session, body.level, body.max_file_size_mb)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid", "message": str(exc)},
        )
    reconfigure_logging(cfg["level"], cfg["max_file_size_mb"])
    write_audit(
        user_id=user.id,
        action="logging.update",
        target_type="system",
        detail={"level": cfg["level"], "max_file_size_mb": cfg["max_file_size_mb"]},
        ip=client_ip(request),
    )
    return ok(cfg)
