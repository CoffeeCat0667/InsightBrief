# -*- coding: utf-8 -*-
"""审计日志契约: GET /api/audit-logs (admin-only 只读查询)。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict


class AuditLogRead(BaseModel):
    """审计日志行 (只读, 不含关联用户信息)。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: Optional[int] = None
    action: str
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    detail: Optional[Dict[str, Any]] = None
    ip: Optional[str] = None
    created_at: Optional[datetime] = None
