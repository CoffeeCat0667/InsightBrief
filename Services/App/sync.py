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

from Config.config import llm_config, services_config
from .models import Source, SystemSetting, Base
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


_LLM_SETTING_KEY = "llm"
_LLM_SENSITIVE_KEYS = ("base_url", "api_key", "model_id")
_LLM_ENV_MAP = {
    "base_url": "IB_LLM_BASE_URL",
    "api_key": "IB_LLM_API_KEY",
    "model_id": "IB_LLM_MODEL_ID",
}


def sync_llm_config(session: Session) -> bool:
    """双向同步: .env <-> system_settings (key="llm"), 仅处理 3 个敏感字段。

    规则:
    - PG 不存在 → 用 .env 值写入 PG
    - PG 存在 → 对每个敏感字段: PG 非空则反写 .env, PG 为空则用 .env 值补写 PG
    - 返回 True 表示发生写入/变更。
    """
    import os

    from Config.config import update_env_file

    env_values = {key: os.environ.get(_LLM_ENV_MAP[key], "") for key in _LLM_SENSITIVE_KEYS}

    setting = session.get(SystemSetting, _LLM_SETTING_KEY)
    if setting is None:
        pg_values = {key: "" for key in _LLM_SENSITIVE_KEYS}
    else:
        cfg = setting.value or {}
        pg_values = {key: str(cfg.get(key, "")) for key in _LLM_SENSITIVE_KEYS}

    env_to_pg = {}
    pg_to_env = {}
    for key in _LLM_SENSITIVE_KEYS:
        pg_val = pg_values[key]
        env_val = env_values[key]
        if pg_val:
            if not env_val or env_val != pg_val:
                pg_to_env[_LLM_ENV_MAP[key]] = pg_val
        else:
            if env_val:
                env_to_pg[key] = env_val

    changed = False

    if env_to_pg:
        if setting is None:
            full_cfg = dict(llm_config())
            full_cfg.update(env_to_pg)
            session.add(
                SystemSetting(
                    key=_LLM_SETTING_KEY,
                    value=full_cfg,
                    description="LLM 配置 (OpenAI V1 统一接口), 来源 .env",
                )
            )
            logger.info("[sync] 用 .env 值创建 LLM 配置: %s", env_to_pg.get("model_id"))
        else:
            cfg = dict(setting.value or {})
            cfg.update(env_to_pg)
            setting.value = cfg
            logger.info("[sync] 用 .env 值补充 PG LLM 字段: %s", list(env_to_pg.keys()))
        changed = True

    if pg_to_env:
        try:
            update_env_file(pg_to_env)
            logger.info("[sync] PG LLM 值反写 .env: %s", list(pg_to_env.keys()))
        except Exception:
            logger.warning("[sync] .env 文件写入失败", exc_info=True)
        changed = True

    return changed


def run_llm_sync() -> bool:
    """独立执行 LLM 配置同步 (建表兜底 + 提交)。供启动引导调用。"""
    ensure_schema()
    with SessionLocal() as session:
        changed = sync_llm_config(session)
        session.commit()
    if changed:
        logger.info("[sync] LLM 配置同步完成")
    return changed


def probe_llm_on_startup() -> bool:
    """启动探测: 发送最小请求验证 LLM key 有效性。返回 True=成功。

    失败仅 warning 日志, 不阻断启动。
    """
    import requests as _requests

    with SessionLocal() as session:
        setting = session.get(SystemSetting, _LLM_SETTING_KEY)
    if setting is None:
        logger.warning("[probe] LLM 配置不存在, 跳过探测")
        return False
    cfg = setting.value or {}
    base_url = str(cfg.get("base_url", "")).rstrip("/")
    api_key = str(cfg.get("api_key", ""))
    model_id = str(cfg.get("model_id", ""))
    if not base_url or not api_key or not model_id:
        logger.warning("[probe] LLM 配置字段不完整, 跳过探测")
        return False

    try:
        resp = _requests.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model_id,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
            timeout=15,
        )
    except _requests.exceptions.Timeout:
        logger.warning("[probe] LLM 连接超时 (15s)")
        return False
    except _requests.exceptions.RequestException as exc:
        logger.warning("[probe] LLM 连接失败: %s", exc)
        return False

    if resp.status_code == 200:
        logger.info("[probe] LLM key 有效, model=%s", model_id)
        return True

    try:
        detail = resp.json()
    except ValueError:
        detail = resp.text[:200]
    logger.warning("[probe] LLM 探测失败 HTTP %d: %s", resp.status_code, str(detail)[:200])
    return False