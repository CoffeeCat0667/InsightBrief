# -*- coding: utf-8 -*-
"""登录鉴权: bcrypt 密码哈希 + JWT(HS256) 签发/校验 + FastAPI 依赖。

- SECRET / 初始管理员配置统一来自 Config/Core.json。
- get_current_user: OAuth2PasswordBearer 解析 Bearer Token -> users 表校验。
- require_admin: 非 admin 角色抛 403。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import Role, User
from .schemas import ErrorCode
from Config.config import core_config

logger = logging.getLogger(__name__)

JWT_SECRET: str = core_config()["auth"]["jwt_secret"]
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_SECONDS = int(core_config()["auth"]["jwt_expire_seconds"])

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/auth/login", auto_error=False
)

_auth_config = core_config()["auth"]
ADMIN_USERNAME = str(_auth_config["admin_username"])
ADMIN_PASSWORD = str(_auth_config["admin_password"])
BCRYPT_MAX_PASSWORD_BYTES = 72
# 仅用于不存在用户的恒时验证; 不是可登录账户的密码哈希。
_DUMMY_PASSWORD_HASH = bcrypt.hashpw(b"InsightBrief login timing dummy", bcrypt.gensalt())


def _password_bytes(password: str) -> bytes:
    """校验 bcrypt 可安全处理的 UTF-8 密码字节数。"""
    encoded = password.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError(f"密码不能超过 {BCRYPT_MAX_PASSWORD_BYTES} 个 UTF-8 字节")
    return encoded


def hash_password(password: str) -> str:
    """bcrypt 哈希; 拒绝超出 bcrypt 72 字节限制的密码, 不静默截断。"""
    return bcrypt.hashpw(_password_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """验证密码; 超长输入也执行 bcrypt 后再返回失败。"""
    try:
        encoded = _password_bytes(password)
    except ValueError:
        # 保持与不存在用户的 dummy 校验相近的成本, 同时拒绝超长密码。
        encoded = b"\x00" * BCRYPT_MAX_PASSWORD_BYTES
        valid_length = False
    else:
        valid_length = True
    try:
        matched = bcrypt.checkpw(encoded, password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False
    return valid_length and matched


def verify_dummy_password(password: str) -> None:
    """对不存在的用户执行同成本 bcrypt, 消除用户名枚举计时侧信道。

    与 verify_password 使用相同的 _password_bytes + bcrypt.checkpw 路径,
    确保无论用户是否存在, bcrypt 计算成本一致。
    """
    try:
        encoded = _password_bytes(password)
    except ValueError:
        encoded = b"\x00" * BCRYPT_MAX_PASSWORD_BYTES
    bcrypt.checkpw(encoded, _DUMMY_PASSWORD_HASH)


def create_access_token(user_id: int) -> str:
    """签发 JWT (sub=user_id, exp=now+ttl)。"""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(seconds=JWT_EXPIRE_SECONDS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[int]:
    """校验 JWT, 返回 user_id; 过期/非法返回 None。"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def get_user_by_username(session: Session, username: str) -> Optional[User]:
    return session.scalar(select(User).where(User.username == username))


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    session: Session = Depends(get_db),
) -> User:
    """登录依赖: 401 语义由统一错误处理器映射为 ErrorCode.UNAUTHORIZED。"""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": ErrorCode.UNAUTHORIZED, "message": "未提供认证 Token"},
        )
    user_id = decode_access_token(token)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": ErrorCode.UNAUTHORIZED, "message": "Token 无效或已过期"},
        )
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": ErrorCode.UNAUTHORIZED, "message": "用户不存在或已禁用"},
        )
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """管理员依赖: 非 admin 抛 403。"""
    if user.role is None or user.role.code != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": ErrorCode.FORBIDDEN, "message": "需要管理员权限"},
        )
    return user


# ================================================================
# 种子数据 (lifespan 调用)
# ================================================================
def seed_roles(session: Session) -> None:
    """roles 表空时插入 admin/user 两角色。"""
    if session.scalar(select(Role).limit(1)) is None:
        session.add_all(
            [
                Role(code="admin", name="管理员"),
                Role(code="user", name="普通用户"),
            ]
        )
        logger.info("[seed] 角色 admin/user 已建")


def seed_admin(session: Session) -> None:
    """无任何用户时创建初始 admin; 新库必须显式提供管理员密码。"""
    if session.scalar(select(User).limit(1)) is not None:
        return
    if not ADMIN_PASSWORD:
        raise RuntimeError(
            "Config/Core.json 未配置 auth.admin_password, 拒绝创建初始管理员"
        )
    admin_role = session.scalar(select(Role).where(Role.code == "admin"))
    session.add(
        User(
            username=ADMIN_USERNAME,
            password_hash=hash_password(ADMIN_PASSWORD),
            role_id=admin_role.id if admin_role else None,
            is_active=True,
        )
    )
    logger.info("[seed] 初始管理员 %r 已建 (密码来自 ADMIN_PASSWORD)", ADMIN_USERNAME)


def seed_all(session: Session) -> None:
    """幂等种子: 角色 + 初始管理员 (先 flush 角色, 供 admin 关联 role_id)。"""
    seed_roles(session)
    session.flush()
    seed_admin(session)
    session.commit()