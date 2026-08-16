# -*- coding: utf-8 -*-
"""配置 -> sources 表同步 (DB 为唯一运行时真相源)。

规则 (用户拍板):
- 每次启动/调用: 以 Config/Services.json 为基准校验 sources 表
- 配置中有而 DB 无 -> 插入
- 双方都有但内容不同 -> 按配置更新
- 配置已删除 -> DB 置 enabled=False 软禁用 (不硬删, 保护 articles 外键)
- 同步幂等: 内容一致重复执行无任何变更
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from Config.config import services_config
from .models import Source, Base
from .db import SessionLocal, engine

logger = logging.getLogger(__name__)

# sources 表业务字段 (除 id 外, 均参与变更对比)
_ROW_FIELDS = ("name", "kind", "platform_ids", "is_domestic", "enabled", "config")


@dataclass
class SyncResult:
    """一次同步的变更摘要。"""

    inserted: List[str] = field(default_factory=list)
    updated: List[str] = field(default_factory=list)
    disabled: List[str] = field(default_factory=list)
    unchanged: int = 0

    @property
    def changed(self) -> int:
        return len(self.inserted) + len(self.updated) + len(self.disabled)

    def summary(self) -> str:
        return (
            f"新增 {len(self.inserted)}, 更新 {len(self.updated)}, "
            f"禁用 {len(self.disabled)}, 无变化 {self.unchanged}"
        )


def sources_from_config() -> List[dict]:
    """将 Config/Services.json 的源注册表映射为 sources 表行字典。

    config 列保留 kind 相关的发现参数 (feeds/url_replace/skip_substrings/
    column_url/link_pattern), 与 discovery 工厂所需字段一一对应。
    """
    discovery = services_config()["discovery"]
    domestic_ids = set(discovery["domestic_source_ids"])
    rows = []
    for spec in discovery["sources"]:
        platform_ids = list(spec.get("platform_ids") or [spec["id"]])
        config = {
            key: value
            for key, value in spec.items()
            if key not in ("id", "name", "kind", "platform_ids")
        }
        rows.append(
            {
                "id": spec["id"],
                "name": spec["name"],
                "kind": spec["kind"],
                "platform_ids": platform_ids,
                "is_domestic": spec["id"] in domestic_ids,
                "enabled": True,
                "config": config,
            }
        )
    return rows


def sync_sources_from_config(session: Session) -> SyncResult:
    """执行同步 (调用方负责 commit)。返回变更摘要。"""
    cfg_rows = {row["id"]: row for row in sources_from_config()}
    result = SyncResult()

    db_rows = {
        row.id: row
        for row in session.scalars(select(Source)).all()
    }

    for source_id, cfg in cfg_rows.items():
        db_row = db_rows.get(source_id)
        if db_row is None:
            session.add(Source(**cfg))
            result.inserted.append(source_id)
            logger.info("[sync] 插入源: %s", source_id)
        elif any(getattr(db_row, key) != cfg[key] for key in _ROW_FIELDS):
            for key in _ROW_FIELDS:
                setattr(db_row, key, cfg[key])
            result.updated.append(source_id)
            logger.info("[sync] 更新源: %s", source_id)
        else:
            result.unchanged += 1

    for source_id, db_row in db_rows.items():
        if source_id not in cfg_rows and db_row.enabled:
            db_row.enabled = False
            result.disabled.append(source_id)
            logger.info("[sync] 禁用源 (配置已删除): %s", source_id)

    return result


def ensure_schema() -> None:
    """建表兜底: Base.metadata 全量 create_all (幂等, 供未跑迁移的环境)。

    alembic 迁移仍是正规通道; 此兜底仅为 CLI/一次性脚本首启可用。
    """
    Base.metadata.create_all(engine)


def run_sources_sync() -> SyncResult:
    """独立执行同步 (建表兜底 + 提交)。供启动脚本与 lifespan 调用。"""
    ensure_schema()
    with SessionLocal() as session:
        result = sync_sources_from_config(session)
        session.commit()
    logger.info("[sync] 完成: %s", result.summary())
    return result