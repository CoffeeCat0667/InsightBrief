# -*- coding: utf-8 -*-
"""抓取结果落库服务: NewsItem/ArticleLink -> articles 相关表。

- make_external_id: 同源去重键 (优先爬虫 news_id, 否则 URL 派生)
- upsert_article: 幂等写入 ((source_id, external_id) 已存在则跳过)
- insert_articles_from_links / crawl_and_ingest: 批量与完整管线
"""
from __future__ import annotations

import hashlib
import importlib
import inspect
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from Core.base import BaseNewsCrawler
from Core.models import ContentItem, NewsItem, NewsMetaInfo
from Config.config import core_config
from .db import SessionLocal
from .models import Article, ArticleContent, ArticleMedia, CrawlTaskArticle

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_EXTERNAL_ID_MAX = 255


def make_external_id(news_item: NewsItem) -> str:
    """去重键: 优先爬虫 news_id (同源内唯一), 否则 URL 哈希派生。"""
    news_id = (news_item.news_id or "").strip()
    if news_id:
        return news_id[:_EXTERNAL_ID_MAX]
    return make_external_id_from_url(news_item.news_url)


def make_external_id_from_url(url: str) -> str:
    """URL 派生去重键 (摘要型源无爬虫 news_id 时的统一规则)。"""
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return f"url:{digest[:48]}"[:_EXTERNAL_ID_MAX]


def find_crawler_class(platform_id: str):
    """按平台 id 定位 Clawer/<cat>/<platform>_news 中的爬虫类 (与 main.py 同款)。"""
    clawer = PROJECT_ROOT / "Clawer"
    if not clawer.is_dir():
        return None
    for cat in clawer.iterdir():
        modname = f"{platform_id}_news"
        if not (cat / modname).is_dir():
            continue
        mod = importlib.import_module(f"Clawer.{cat.name}.{modname}.{modname}")
        for _, cls in inspect.getmembers(mod, inspect.isclass):
            if (
                issubclass(cls, BaseNewsCrawler)
                and cls.__module__ == mod.__name__
                and cls is not BaseNewsCrawler
            ):
                return cls
    return None


def upsert_article(
    session: Session,
    source_id: str,
    news_item: NewsItem,
    *,
    external_id: Optional[str] = None,
    commit: bool = False,
) -> tuple[Optional[Article], bool]:
    """幂等写入一篇文章; 已存在返回 (existing, False), 新写入返回 (article, True)。

    更新策略: 已存在整体跳过 (不重抓重盖, 保留首次抓取结果与历史)。
    """
    ext = external_id or make_external_id(news_item)
    existing = session.scalar(
        select(Article).where(
            Article.source_id == source_id, Article.external_id == ext
        )
    )
    if existing is not None:
        return existing, False

    existing = session.scalar(
        select(Article).where(Article.url == news_item.news_url)
    )
    if existing is not None:
        return existing, False

    meta = news_item.meta_info
    article = Article(
        source_id=source_id,
        external_id=ext,
        url=news_item.news_url,
        title=news_item.title,
        subtitle=news_item.subtitle,
        author_name=meta.author_name or "",
        author_url=meta.author_url or None,
        publish_time=meta.publish_time or "",
        content="\n".join(news_item.texts) or None,
        language=meta.extra.get("language") if isinstance(meta.extra, dict) else None,
        crawled_at=datetime.now(),
    )
    if news_item.contents:
        article.contents = [
            ArticleContent(
                seq=idx,
                type=item.type.value if hasattr(item.type, "value") else str(item.type),
                content=item.content,
                desc=item.desc or None,
            )
            for idx, item in enumerate(news_item.contents)
        ]
    if news_item.images or news_item.videos:
        article.media = [
            ArticleMedia(kind="image", url=url) for url in (news_item.images or [])
        ] + [
            ArticleMedia(kind="video", url=url) for url in (news_item.videos or [])
        ]
    session.add(article)
    if commit:
        session.commit()
    return article, True


def _platform_ids_of(source_id: str) -> List[str]:
    from Services.discovery import get_source

    try:
        return list(get_source(source_id).platform_ids)
    except Exception:
        return [source_id]


def _crawler_for_link(link, platform_ids: List[str]):
    """按链接平台匹配爬虫类; 无爬虫/无法识别则 None (交由摘要路径)。"""
    from Services.discovery import detect_platform

    platform = detect_platform(link.url)
    if platform is None:
        return None
    cls = find_crawler_class(platform)
    if cls is None:
        return None
    return cls(link.url, platform_id=platform)


def _summary_item_from_link(link) -> NewsItem:
    """摘要型源: RSS 自带全文直接构 NewsItem (无详情页可抓)。"""
    return NewsItem(
        title=link.title or "",
        news_url=link.url,
        news_id=make_external_id_from_url(link.url),
        meta_info=NewsMetaInfo(publish_time=link.publish_time),
        contents=[ContentItem(type="text", content=link.content or "")],
    )


def insert_articles_from_links(
    session: Session,
    source_id: str,
    links,
    *,
    max_items: int = 30,
    on_progress=None,
    crawl_task_id: Optional[int] = None,
) -> Dict[str, int]:
    """批量落库: 摘要型源直接入库, 其余逐篇抓详情页落库 (单篇失败不中断)。

    on_progress(processed, total): 每处理一篇 (含失败/跳过) 调用一次, 供
    任务运行时推送源内文章级进度。
    返回统计 {discovered, inserted, existed, failed}。
    """
    stats = {"discovered": len(links), "inserted": 0, "existed": 0, "failed": 0}
    platform_ids = _platform_ids_of(source_id)
    summary_only = not any(find_crawler_class(p) for p in platform_ids)
    total = min(len(links), max_items)
    processed = 0

    for link in list(links)[:max_items]:
        try:
            if summary_only:
                item = _summary_item_from_link(link)
            else:
                crawler = _crawler_for_link(link, platform_ids)
                if crawler is None:
                    stats["failed"] += 1
                    logger.warning("[%s] 无匹配爬虫, 跳过: %s", source_id, link.url)
                    continue
                item = crawler.run(persist=False)
            article, created = upsert_article(session, source_id, item)
            if created:
                session.flush()
            outcome = "inserted" if created else "existed"
            stats[outcome] += 1
            if crawl_task_id is not None and article is not None:
                existing_link = session.scalar(
                    select(CrawlTaskArticle).where(
                        CrawlTaskArticle.crawl_task_id == crawl_task_id,
                        CrawlTaskArticle.article_id == article.id,
                    )
                )
                if existing_link is None:
                    session.add(
                        CrawlTaskArticle(
                            crawl_task_id=crawl_task_id,
                            article_id=article.id,
                            outcome=outcome,
                        )
                    )
        except Exception as exc:  # 单篇失败不影响批次
            session.rollback()
            logger.warning("[%s] 落库失败 %s: %s", source_id, link.url, exc)
            stats["failed"] += 1
        finally:
            processed += 1
            if on_progress:
                on_progress(processed, total)
    return stats


def crawl_and_ingest(
    source_id: str,
    *,
    max_items: int = 30,
    on_progress=None,
    crawl_task_id: Optional[int] = None,
) -> Dict[str, int]:
    """完整管线: discover -> 逐篇抓取 -> 落库 (独立会话)。

    on_progress(processed, total): 源内文章级进度回调 (透传 insert_articles_from_links)。
    """
    from Services.discovery import discover_links

    links = discover_links(source_id)
    if not links:
        logger.info("[%s] 未发现链接", source_id)
        return {"discovered": 0, "inserted": 0, "existed": 0, "failed": 0}
    with SessionLocal() as session:
        stats = insert_articles_from_links(
            session,
            source_id,
            links,
            max_items=max_items,
            on_progress=on_progress,
            crawl_task_id=crawl_task_id,
        )
        session.commit()
    logger.info("[%s] 落库完成: %s", source_id, stats)
    return stats