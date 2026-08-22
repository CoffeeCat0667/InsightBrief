# -*- coding: utf-8 -*-
"""reconfigure_logging(): 即时重配 Python logging，无需重启进程。"""
from __future__ import annotations

import logging
import logging.handlers
import os

_LOG_FILE = os.path.abspath("app.log")
_BACKUP_COUNT = 5

_root = logging.getLogger()
_file_handler: logging.handlers.RotatingFileHandler | None = None


def reconfigure_logging(level: str, max_file_size_mb: int) -> None:
    """清理旧 handler → 新建 RotatingFileHandler → 同步子 logger 级别。"""
    global _file_handler

    level_int = getattr(logging, level.upper(), logging.INFO)
    max_bytes = max_file_size_mb * 1024 * 1024

    # 移除旧的 file handler
    if _file_handler is not None:
        _root.removeHandler(_file_handler)
        _file_handler.close()
        _file_handler = None

    # 新建 RotatingFileHandler
    _file_handler = logging.handlers.RotatingFileHandler(
        _LOG_FILE,
        maxBytes=max_bytes,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    _file_handler.setLevel(level_int)
    _file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    _root.addHandler(_file_handler)

    # 根 logger 级别: 至少 INFO，保证 StreamHandler (uvicorn) 有输出
    _root.setLevel(min(level_int, logging.INFO))

    # 同步常用子 logger 级别
    for name in (
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
        "sqlalchemy.engine",
        "httpx",
    ):
        logging.getLogger(name).setLevel(level_int)
