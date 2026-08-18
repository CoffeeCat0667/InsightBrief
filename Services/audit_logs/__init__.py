# -*- coding: utf-8 -*-
"""审计日志写入: 关键操作留痕 (audit_logs 表, 只增不删)。

- write_audit: 独立会话提交, 任何失败只记日志不向上抛 — 审计绝不炸主业务。
- client_ip: 仅当直连地址位于配置的可信反代名单时才采信 X-Forwarded-For;
  未配置可信反代时始终记录 socket 对端地址, 防止客户端伪造审计 IP。
- action 命名规范: {object}.{verb} (失败加 _failed 后缀), 见各调用点。
"""
from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any, Dict, Optional

from fastapi import Request

from ..App.db import SessionLocal
from ..App.models import AuditLog

logger = logging.getLogger(__name__)


def client_ip(request: Request) -> Optional[str]:
    """采集客户端 IP; 只信任显式配置的反代发送的 X-Forwarded-For。"""
    peer_ip = request.client.host if request.client is not None else None
    if peer_ip is None:
        return None
    from Config.config import core_config

    trusted_proxy_ips = set(core_config()["auth"]["trusted_proxy_ips"])
    if peer_ip not in trusted_proxy_ips:
        return peer_ip
    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return peer_ip
    first = forwarded.split(",")[0].strip()
    return first or peer_ip


def write_audit(
    *,
    user_id: Optional[int] = None,
    action: str,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    detail: Optional[Dict[str, Any]] = None,
    ip: Optional[str] = None,
) -> bool:
    """写入一条审计日志 (独立会话 + 提交)。

    调用点无需 try/except: 任何异常(连接/序列化等)仅告警返回 False,
    主业务事务不受影响。detail 深拷贝, 防调用方后续改动污染落库内容。
    """
    try:
        with SessionLocal() as session:
            session.add(
                AuditLog(
                    user_id=user_id,
                    action=action,
                    target_type=target_type,
                    target_id=str(target_id) if target_id is not None else None,
                    detail=deepcopy(detail) if detail is not None else None,
                    ip=ip,
                )
            )
            session.commit()
        return True
    except Exception:
        logger.exception("[audit] 写入失败 action=%r", action)
        return False
