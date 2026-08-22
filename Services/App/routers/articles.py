# -*- coding: utf-8 -*-
"""文章查询端点: 列表/搜索/详情 + 平台列表。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..models import Article, Source, User
from ..schemas import (
    ArticleContenItem,
    ArticleDetail,
    ArticleListItem,
    ArticleListParams,
    Page,
    PageParams,
    PlatformRead,
    ok,
)
from ..security import get_current_user

router = APIRouter(prefix="/api/articles", tags=["articles"])
platforms_router = APIRouter(prefix="/api/platforms", tags=["platforms"])

_SOURCE_CN_NAMES = {
    "bbc": "BBC News",
    "cnn": "CNN",
    "xinhua": "新华网",
    "people": "人民网",
    "jfjb": "解放军报(中国军网)",
}


def _source_name(session: Session, source_id: str) -> str:
    return (session.get(Source, source_id) or Source(id=source_id, name=source_id)).name


def _page_of(session: Session, stmt, page: int, page_size: int):
    total = (
        session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
        or 0
    )
    rows = (
        session.scalars(
            stmt.order_by(Article.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .all()
    )
    items = [ArticleListItem.model_validate(r) for r in rows]
    if items:
        ids = {item.source_id for item in items}
        names = {
            s.id: s.name
            for s in session.scalars(select(Source).where(Source.id.in_(ids))).all()
        }
        for item in items:
            item.source_name = names.get(item.source_id, item.source_id)
    return Page[ArticleListItem](
        items=items, total=total, page=page, page_size=page_size
    )


@router.get("")
def list_articles(
    params: ArticleListParams = Depends(),
    page: PageParams = Depends(),
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """文章列表 (分页 + 源/分类/时间筛选)。"""
    stmt = select(Article)
    if params.source_id:
        stmt = stmt.where(Article.source_id == params.source_id)
    if params.category:
        stmt = stmt.where(Article.category == params.category.value)
    if params.start_time:
        stmt = stmt.where(Article.created_at >= params.start_time)
    if params.end_time:
        stmt = stmt.where(Article.created_at <= params.end_time)
    return ok(_page_of(session, stmt, page.page, page.page_size))


@router.get("/search")
def search_articles(
    keyword: str,
    in_original: bool = True,
    source_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """关键词搜索 (原文/译文标题或正文, ILIKE 模糊)。"""
    needle = f"%{keyword}%"
    if in_original:
        cond = or_(Article.title.ilike(needle), Article.content.ilike(needle))
    else:
        cond = or_(
            Article.translated_title.ilike(needle),
            Article.translated_content.ilike(needle),
        )
    stmt = select(Article).where(cond)
    if source_id:
        stmt = stmt.where(Article.source_id == source_id)
    return ok(_page_of(session, stmt, page, page_size))


@router.get("/stats-by-day")
def stats_by_day(
    day: str,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """某一天各新闻源的文章数量。"""
    from datetime import date as _date, datetime, timedelta
    day_date = _date.fromisoformat(day)
    next_day = day_date + timedelta(days=1)
    day_start = datetime.combine(day_date, datetime.min.time())
    day_end = datetime.combine(next_day, datetime.min.time())
    stmt = (
        select(Article.source_id, func.count().label("count"))
        .where(Article.created_at >= day_start, Article.created_at < day_end)
        .group_by(Article.source_id)
        .order_by(func.count().desc())
    )
    rows = session.execute(stmt).all()
    names = {s.id: s.name for s in session.scalars(select(Source)).all()}
    return ok([
        {"source_id": r.source_id, "source_name": names.get(r.source_id, r.source_id), "count": r.count}
        for r in rows
    ])


@router.get("/stats-by-source")
def stats_by_source(
    source_id: str,
    days: int = 30,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """某新闻源最近 N 天每天的文章数量。"""
    from datetime import datetime, timedelta
    cutoff = datetime.now() - timedelta(days=days)
    stmt = (
        select(func.date(Article.created_at).label("day"), func.count().label("count"))
        .where(Article.source_id == source_id, Article.created_at >= cutoff)
        .group_by("day")
        .order_by("day")
    )
    rows = session.execute(stmt).all()
    return ok([
        {"day": str(r.day), "count": r.count}
        for r in rows
    ])


@router.get("/{article_id}")
def get_article(
    article_id: int,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """文章详情 (含正文片段/媒体)。"""
    article = session.scalar(
        select(Article)
        .options(joinedload(Article.contents), joinedload(Article.media))
        .where(Article.id == article_id)
    )
    if article is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"文章 {article_id} 不存在"},
        )
    detail = ArticleDetail.model_validate(article)
    detail.source_name = _source_name(session, article.source_id)
    detail.contents = [
        ArticleContenItem(seq=c.seq, type=c.type, content=c.content, desc=c.desc)
        for c in sorted(article.contents, key=lambda x: x.seq)
    ]
    return ok(detail)


@platforms_router.get("")
def list_platforms(
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """平台列表: 聚合自 sources.platform_ids + Clawer 目录分类。"""
    merged: dict[str, dict] = {}
    rows = session.scalars(select(Source).where(Source.enabled.is_(True))).all()
    for row in rows:
        for pid in row.platform_ids or []:
            item = merged.setdefault(
                pid,
                {
                    "platform_id": pid,
                    "name": _SOURCE_CN_NAMES.get(pid, row.name),
                    "source_ids": [],
                },
            )
            if row.id not in item["source_ids"]:
                item["source_ids"].append(row.id)

    clawer = Path(__file__).resolve().parents[3] / "Clawer"
    if clawer.is_dir():
        for cat in clawer.iterdir():
            if not cat.is_dir() or cat.name == "__pycache__":
                continue
            for entry in cat.iterdir():
                if entry.is_dir() and entry.name.endswith("_news"):
                    pid = entry.name[:-5]
                    if pid in merged:
                        merged[pid]["category_label"] = cat.name

    return ok([PlatformRead(**info) for info in merged.values()])