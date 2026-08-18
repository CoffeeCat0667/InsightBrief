# -*- coding: utf-8 -*-
"""审计日志端点: GET /api/audit-logs (admin-only, 只读查询)。

审计写入在 Services/audit_logs (write_audit); 本端点仅提供查询面,
供管理员审计留痕 (action/user_id 筛选 + 分页, 按时间倒序)。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AuditLog, User
from ..schemas import AuditLogRead, Page, PageParams, ok
from ..security import require_admin

router = APIRouter(prefix="/api/audit-logs", tags=["audit-logs"])


@router.get("")
def list_audit_logs(
    action: Optional[str] = None,
    user_id: Optional[int] = None,
    page: PageParams = Depends(),
    session: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """审计日志列表 (admin); 可选 action/user_id 筛选, 按时间倒序。"""
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
    total = (
        session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
        or 0
    )
    rows = session.scalars(
        stmt.order_by(AuditLog.id.desc())
        .offset((page.page - 1) * page.page_size)
        .limit(page.page_size)
    ).all()
    return ok(
        Page[AuditLogRead](
            items=[AuditLogRead.model_validate(r) for r in rows],
            total=total,
            page=page.page,
            page_size=page.page_size,
        )
    )
