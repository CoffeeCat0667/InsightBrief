# -*- coding: utf-8 -*-
"""登录鉴权: bcrypt 密码哈希 + JWT(HS256) 签发/校验 + FastAPI 依赖。

- SECRET: JWT_SECRET 环境变量 (生产必配); 未配置时随机生成 (重启失效, 仅开发)。
- get_current_user: OAuth2PasswordBearer 解析 Bearer Token -> users 表校验。
- require_admin: 非 admin 角色抛 403。
"""
from __future__ import annotations

import logging
import os
import secrets
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

logger = logging.getLogger(__name__)

JWT_SECRET: str = os.environ.get("JWT_SECRET") or ""
if not JWT_SECRET:
    JWT_SECRET = secrets.token_hex(32)
    logger.warning("JWT_SECRET 未配置, 使用随机密钥 (进程重启后所有 Token 失效; 生产环境请设置 JWT_SECRET)")

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_SECONDS = int(os.environ.get("JWT_EXPIRE_SECONDS", "86400"))

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/auth/login", auto_error=False
)

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123456")


def hash_password(password: str) -> str:
    """bcrypt 哈希 (bcrypt 4.x 仅处理前 72 字节, 超长截断)。"""
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(
        password.encode("utf-8")[:72], password_hash.encode("utf-8")
    )


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
    """无任何用户时创建初始 admin (凭据来自 ADMIN_* 环境变量)。"""
    if session.scalar(select(User).limit(1)) is not None:
        return
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