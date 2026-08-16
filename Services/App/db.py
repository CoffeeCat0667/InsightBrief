# -*- coding: utf-8 -*-
"""数据库引擎与会话管理 (DSN 来自 Config/db.json, 可被 DB_DSN 环境变量覆盖)。

注意: 密码中的 @ 在 DSN 中须 percent-encode 为 %40 (见 Config/db.json)。
"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from Config.config import db_config

_CFG = db_config()["postgres"]

engine = create_engine(
    _CFG["dsn"],
    pool_size=int(_CFG["pool_size"]),
    max_overflow=int(_CFG["max_overflow"]),
    pool_pre_ping=True,
    echo=bool(_CFG.get("echo", False)),
)

SessionLocal = sessionmaker(
    bind=engine, autoflush=False, expire_on_commit=False
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖注入用会话生成器 (路由步骤接入)。"""
    with SessionLocal() as session:
        yield session