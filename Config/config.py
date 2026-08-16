# -*- coding: utf-8 -*-
"""统一配置加载: Config/*.json -> dict, 环境变量覆盖 + 必填校验。

与后端 backend/config.py 对齐: 配置文件为唯一事实来源, 环境变量覆盖
既有默认行为 (如 CRAWL_PROXY 覆盖代理地址, 设为空串则禁用代理)。
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

CONFIG_DIR = Path(__file__).resolve().parent

_CORE_ENV_PATHS = {
    ("proxy", "default"): "CRAWL_PROXY",
}

_DB_ENV_PATHS = {
    ("postgres", "dsn"): "DB_DSN",
    ("redis", "host"): "REDIS_HOST",
    ("redis", "port"): "REDIS_PORT",
    ("redis", "db"): "REDIS_DB",
    ("redis", "password"): "REDIS_PASSWORD",
}


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


def _apply_env(
    data: Dict[str, Any],
    env_paths: Mapping[tuple[str, ...], str],
) -> Dict[str, Any]:
    """按点路径将环境变量值覆盖到配置字典 (未设置则保留文件值)。"""
    for keys, env_var in env_paths.items():
        if env_var not in os.environ:
            continue
        node = data
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = os.environ[env_var].strip()
    return data


def _require(data: Dict[str, Any], path: str, name: str) -> None:
    """校验必填键存在且非空, 缺失抛 ConfigError。"""
    node = data
    for key in path.split("."):
        if not isinstance(node, dict) or key not in node or node[key] is None:
            raise ConfigError(f"{name} 缺少必填配置: {path}")
        node = node[key]


@lru_cache(maxsize=None)
def core_config() -> Dict[str, Any]:
    """Core.json: 代理/UA/超时重试/路径/playwright/generic 阈值。"""
    data = _apply_env(_load("Core"), _CORE_ENV_PATHS)
    for key in ("proxy.default", "user_agent", "fetch.attempts", "paths.save_dir"):
        _require(data, key, "Core.json")
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
    """统一代理入口: CRAWL_PROXY 覆盖 Core.json, 空串禁用代理 (None)。"""
    proxy = core_config()["proxy"]["default"].strip()
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


@lru_cache(maxsize=None)
def db_config() -> Dict[str, Any]:
    """db.json: PostgreSQL / Redis 连接配置, 支持 DB_DSN/REDIS_* 环境变量覆盖。"""
    data = _apply_env(_load("db"), _DB_ENV_PATHS)
    _require(data, "postgres.dsn", "db.json")
    _require(data, "postgres.pool_size", "db.json")
    _require(data, "postgres.max_overflow", "db.json")
    _require(data, "redis.host", "db.json")
    return data