# -*- coding: utf-8 -*-
"""articles / article_contents / article_media: 文章主数据与结构化片段。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class Article(TimestampMixin, Base):
    """
    抓取到的文章 (UNIQUE(source_id, external_id) 用于历史导入去重)。

    - external_id: 爬虫 get_article_id() / URL 派生, 同源内唯一
    - category: 简报四分类 politics/economy/culture/technology
    - translated_*: 简报步骤填写的译文
    """

    __tablename__ = "articles"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_articles_source_external"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    subtitle: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    author_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    author_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    publish_time: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    language: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    translated_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    translated_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    crawled_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)


class ArticleContent(Base):
    """文章结构化正文片段 (原文逐段, 对应旧模型 ContentItem)。"""

    __tablename__ = "article_contents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    type: Mapped[str] = mapped_column(String(16), nullable=False, default="text")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    desc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ArticleMedia(Base):
    """文章媒体资源 (图片/视频独立存放)。"""

    __tablename__ = "article_media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)