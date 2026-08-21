# -*- coding: utf-8 -*-
"""统一配置加载: Config/*.json -> dict, JSON 唯一来源 + 必填校验。

与后端配置对齐: 配置文件为唯一事实来源。所有运行参数和凭证均从 JSON 读取，后续可再迁移到 `.env` 或 secrets。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

CONFIG_DIR = Path(__file__).resolve().parent

class ConfigError(ValueError):
    """配置文件缺失/非法/缺必填键时抛出。"""


def _load(name: str) -> Dict[str, Any]:
    """读取 Config/<name>.json, 解析失败抛 ConfigError。"""
    path = CONFIG_DIR / f"{name}.json"
    if not path.is_file():
        raise ConfigError(f"配置文件缺失: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"配置文件解析失败: {path}: {exc}") from exc


def _require(data: Dict[str, Any], path: str, name: str) -> None:
    """校验必填键存在且非空, 缺失抛 ConfigError。"""
    node = data
    for key in path.split("."):
        if not isinstance(node, dict) or key not in node or node[key] is None:
            raise ConfigError(f"{name} 缺少必填配置: {path}")
        node = node[key]


@lru_cache(maxsize=None)
def core_config() -> Dict[str, Any]:
    """Core.json: 非秘密运行配置与 JSON 内置鉴权/网页配置。"""
    data = _load("Core")
    for key in (
        "user_agent",
        "fetch.attempts",
        "paths.save_dir",
        "proxy.default",
        "auth.jwt_secret",
        "auth.jwt_expire_seconds",
        "auth.admin_username",
        "auth.admin_password",
        "auth.login_rate_limit.max_attempts",
        "auth.login_rate_limit.window_seconds",
        "auth.trusted_proxy_ips",
        "web.disable_docs",
    ):
        _require(data, key, "Core.json")
    try:
        limit = int(data["auth"]["login_rate_limit"]["max_attempts"])
        window = int(data["auth"]["login_rate_limit"]["window_seconds"])
        expire = int(data["auth"]["jwt_expire_seconds"])
    except (TypeError, ValueError, KeyError) as exc:
        raise ConfigError("Core.json auth 配置必须为整数") from exc
    if limit < 1 or window < 1 or expire < 1:
        raise ConfigError("Core.json auth 配置必须为正整数")
    if not isinstance(data["auth"]["trusted_proxy_ips"], list):
        raise ConfigError("Core.json auth.trusted_proxy_ips 必须为列表")
    data["auth"]["login_rate_limit"] = {
        "max_attempts": limit,
        "window_seconds": window,
    }
    data["auth"]["jwt_expire_seconds"] = expire
    data["web"]["disable_docs"] = bool(data["web"]["disable_docs"])
    return data


@lru_cache(maxsize=None)
def clawer_config() -> Dict[str, Any]:
    """Clawer.json: 平台级覆盖 (base_url/xpath/UA/抓取策略)。"""
    data = _load("Clawer")
    _require(data, "platforms", "Clawer.json")
    return data


@lru_cache(maxsize=None)
def platform_config(platform_id: str) -> Dict[str, Any]:
    """单个平台的覆盖配置; 平台未登记返回空 dict。"""
    return clawer_config()["platforms"].get(platform_id, {})


@lru_cache(maxsize=None)
def services_config() -> Dict[str, Any]:
    """Services.json: discovery 注册表 + translator 配置。"""
    data = _load("Services")
    for key in (
        "translator.chunk_size",
        "discovery.platform_patterns",
        "discovery.sources",
    ):
        _require(data, key, "Services.json")
    return data


def get_proxy_config() -> Optional[Mapping[str, str]]:
    """统一代理入口: Core.json 为空字符串时禁用代理 (None)。"""
    proxy = core_config()["proxy"]["default"].strip()
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


@lru_cache(maxsize=None)
def db_config() -> Dict[str, Any]:
    """db.json: PostgreSQL / Redis 连接配置，JSON 为唯一来源。"""
    data = _load("db")
    _require(data, "postgres.dsn", "db.json")
    _require(data, "postgres.pool_size", "db.json")
    _require(data, "postgres.max_overflow", "db.json")
    _require(data, "redis.host", "db.json")
    _require(data, "redis.port", "db.json")
    _require(data, "redis.db", "db.json")
    return data


@lru_cache(maxsize=None)
def llm_config() -> Dict[str, Any]:
    """LLM.json: 简报系统 LLM 配置 (统一 OpenAI V1 接口, 不区分提供商)。

    仅由 sync.py 读取注入 PG (system_settings key="llm"); 应用实现一律
    只读 PG, 不直接读此文件。
    """
    data = _load("LLM")
    for key in (
        "base_url",
        "api_key",
        "model_id",
        "timeout_s",
        "retry.attempts",
        "operators.classify.categories",
    ):
        _require(data, key, "LLM.json")
    return data