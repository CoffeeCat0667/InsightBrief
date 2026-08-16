# -*- coding: utf-8 -*-
"""Alembic 迁移环境: DSN 来自 Config/db.json (复用 App.db engine, 避开
alembic.ini 的 ConfigParser 插值对 %40 等转义字符的误解)。"""
from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Config.config import db_config  # noqa: E402
from Services.App.models import Base  # noqa: E402
from Services.App.db import engine  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

PG_DSN = db_config()["postgres"]["dsn"]
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式: 仅生成 SQL 不连库。"""
    context.configure(
        url=PG_DSN,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式: 复用 App.db 的连接引擎执行迁移。"""
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()