# -*- coding: utf-8 -*-
"""文章/平台契约: GET /api/articles(列表/详情/搜索) + GET /api/platforms。"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ArticleCategory(str, Enum):
    """简报四分类 (政治/经济/文化/科技)。"""

    POLITICS = "politics"
    ECONOMY = "economy"
    CULTURE = "culture"
    TECHNOLOGY = "technology"


class ArticleListItem(BaseModel):
    """文章列表项 (不含正文)。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: str
    source_name: Optional[str] = None
    title: str
    subtitle: Optional[str] = None
    url: str
    author_name: str = ""
    publish_time: str = ""
    category: Optional[ArticleCategory] = None
    translated_title: Optional[str] = None
    summary: Optional[str] = None
    created_at: Optional[datetime] = None


class ArticleListParams(BaseModel):
    """GET /api/articles 筛选参数 (Query 注入)。"""

    source_id: Optional[str] = None
    category: Optional[ArticleCategory] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


class ArticleContenItem(BaseModel):
    """正文片段 (原文与译文并存说明: 原文在 content, 译文在翻译步骤填)。"""

    model_config = ConfigDict(from_attributes=True)

    seq: int
    type: str = "text"
    content: str
    desc: Optional[str] = None


class ArticleMediaRead(BaseModel):
    """媒体资源 (图片/视频)。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    url: str
    caption: Optional[str] = None


class ArticleDetail(ArticleListItem):
    """文章详情 (含正文/媒体/译文全文)。"""

    content: Optional[str] = None
    translated_content: Optional[str] = None
    language: Optional[str] = None
    author_url: Optional[str] = None
    crawled_at: Optional[datetime] = None
    contents: List[ArticleContenItem] = Field(default_factory=list)
    media: List[ArticleMediaRead] = Field(default_factory=list)


class ArticleSearchParams(BaseModel):
    """GET /api/articles/search 搜索参数。"""

    keyword: str = Field(min_length=1, max_length=128)
    in_original: bool = True  # 是否搜索原文; False 则只搜译文
    source_id: Optional[str] = None


class PlatformRead(BaseModel):
    """GET /api/platforms 平台列表项 (聚合自源 platform_ids + 爬虫目录)。"""

    platform_id: str
    name: str
    category_label: Optional[str] = None
    source_ids: List[str] = Field(default_factory=list)