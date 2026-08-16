# -*- coding: utf-8 -*-
"""sources 表: 新闻源注册表 (DB 为唯一运行时真相源, 配置仅作启动同步基准)。"""
from __future__ import annotations

from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class Source(TimestampMixin, Base):
    """
    新闻源 (27 个种子源来自 Config/Services.json, 经 App.sync 同步):

    - kind: "rss" | "column" | "custom"
    - config: rss -> {"feeds", "url_replace"?", "skip_substrings"?};
              column -> {"column_url", "link_pattern"};
              custom -> {}
    - is_domestic: 国内/外媒标记 (替代配置 domestic_source_ids)
    - enabled: 配置中已删除的源软禁用, 不硬删 (保护 articles 外键)
    """

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    platform_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    is_domestic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)