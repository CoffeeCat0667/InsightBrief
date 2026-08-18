# -*- coding: utf-8 -*-
"""源管理端点: GET/POST /api/sources, PATCH/DELETE /api/sources/{id}。

- GET 需登录; POST/PATCH/DELETE 需 admin (权限 401/403 语义)。
- 注意: 每次启动 sync 会以 Config/Services.json 校验本表, 配置内源的
  手工改动将在下次启动被配置覆盖回写 (拍板规则)。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...audit_logs import client_ip, write_audit
from ..db import get_db
from ..models import Source, User
from ..schemas import ErrorCode, Page, PageParams, SourceCreate, SourceRead, SourceUpdate, ok
from ..security import get_current_user, require_admin

router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("")
def list_sources(
    params: PageParams = Depends(),
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """源列表 (分页, 含软禁源)。"""
    total = session.scalar(select(func.count()).select_from(Source)) or 0
    rows = (
        session.scalars(
            select(Source)
            .order_by(Source.enabled.desc(), Source.id)
            .offset((params.page - 1) * params.page_size)
            .limit(params.page_size)
        )
        .all()
    )
    return ok(
        Page[SourceRead](
            items=[SourceRead.model_validate(r) for r in rows],
            total=total,
            page=params.page,
            page_size=params.page_size,
        )
    )


@router.post("")
def create_source(
    body: SourceCreate,
    request: Request,
    session: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """新增源 (admin); id 冲突返回 409。"""
    if session.get(Source, body.id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": ErrorCode.CONFLICT, "message": f"源 {body.id} 已存在"},
        )
    source = Source(**body.model_dump())
    session.add(source)
    session.commit()
    write_audit(
        user_id=user.id,
        action="source.create",
        target_type="source",
        target_id=body.id,
        detail=body.model_dump(),
        ip=client_ip(request),
    )
    return ok(SourceRead.model_validate(source))


@router.get("/{source_id}")
def get_source(
    source_id: str,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    source = session.get(Source, source_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": ErrorCode.NOT_FOUND, "message": f"源 {source_id} 不存在"},
        )
    return ok(SourceRead.model_validate(source))


@router.patch("/{source_id}")
def update_source(
    source_id: str,
    body: SourceUpdate,
    request: Request,
    session: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """更新源 (admin); 配置内源的改动会在下次启动 sync 被配置覆盖。"""
    source = session.get(Source, source_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": ErrorCode.NOT_FOUND, "message": f"源 {source_id} 不存在"},
        )
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(source, key, value)
    session.commit()
    write_audit(
        user_id=user.id,
        action="source.update",
        target_type="source",
        target_id=source_id,
        detail=changes,
        ip=client_ip(request),
    )
    return ok(SourceRead.model_validate(source))


@router.delete("/{source_id}")
def delete_source(
    source_id: str,
    request: Request,
    session: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """删除源 (admin); 被文章引用时 FK 阻止硬删 -> 自动转软禁用。"""
    source = session.get(Source, source_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": ErrorCode.NOT_FOUND, "message": f"源 {source_id} 不存在"},
        )
    try:
        session.delete(source)
        session.commit()
        write_audit(
            user_id=user.id,
            action="source.delete",
            target_type="source",
            target_id=source_id,
            detail={"name": source.name},
            ip=client_ip(request),
        )
        return ok({"deleted": source_id})
    except IntegrityError:
        session.rollback()
        source = session.get(Source, source_id)
        source.enabled = False
        session.commit()
        write_audit(
            user_id=user.id,
            action="source.disable",
            target_type="source",
            target_id=source_id,
            detail={"name": source.name, "reason": "被文章引用, 已软禁用"},
            ip=client_ip(request),
        )
        return ok({"deleted": None, "disabled": source_id, "reason": "被文章引用, 已软禁用"})