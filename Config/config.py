# -*- coding: utf-8 -*-
"""统一配置加载: Config/*.json (非敏感) + .env (敏感) -> dict, 必填校验。

敏感字段 (JWT secret、管理员凭据、数据库 DSN、Redis 密码、LLM 凭证)
仅从 .env 读取 (python-dotenv 加载到 os.environ); JSON 不含敏感值。
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

CONFIG_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = CONFIG_DIR.parent

# ── .env 加载 (项目根目录, 不覆盖已有环境变量) ──────────────────
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(_PROJECT_ROOT / ".env", override=False)
except ImportError:
    pass


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
    """校验必填键存在且非空, 缺失或空字符串抛 ConfigError。"""
    node = data
    for key in path.split("."):
        if not isinstance(node, dict) or key not in node or node[key] is None:
            raise ConfigError(f"{name} 缺少必填配置: {path}")
        node = node[key]
    if node == "":
        raise ConfigError(f"{name} 配置值为空: {path}")


def _env_required(name: str) -> str:
    """从环境变量读取必填敏感字段; 缺失或空则抛 ConfigError。"""
    val = os.environ.get(name, "")
    if not val:
        raise ConfigError(f"敏感字段未配置 (请在 .env 中设置 {name})")
    return val


@lru_cache(maxsize=None)
def core_config() -> Dict[str, Any]:
    """Core.json (非敏感) + .env (敏感) 合并配置。

    .env 敏感字段: IB_PROXY_DEFAULT, IB_JWT_SECRET, IB_JWT_EXPIRE_SECONDS,
                    IB_ADMIN_USERNAME, IB_ADMIN_PASSWORD
    """
    data = _load("Core")

    # ── 非敏感字段必填校验 ──
    for key in (
        "user_agent",
        "fetch.attempts",
        "paths.save_dir",
        "auth.login_rate_limit.max_attempts",
        "auth.login_rate_limit.window_seconds",
        "auth.trusted_proxy_ips",
        "web.disable_docs",
    ):
        _require(data, key, "Core.json")

    # ── 敏感字段: 仅从 .env 读取 ──
    data["proxy"] = {"default": _env_required("IB_PROXY_DEFAULT")}
    data["auth"]["jwt_secret"] = _env_required("IB_JWT_SECRET")
    data["auth"]["admin_username"] = _env_required("IB_ADMIN_USERNAME")
    data["auth"]["admin_password"] = _env_required("IB_ADMIN_PASSWORD")

    try:
        limit = int(data["auth"]["login_rate_limit"]["max_attempts"])
        window = int(data["auth"]["login_rate_limit"]["window_seconds"])
        expire_str = os.environ.get("IB_JWT_EXPIRE_SECONDS", "")
        expire = int(expire_str) if expire_str else int(data["auth"]["jwt_expire_seconds"])
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
    """统一代理入口: 空字符串时禁用代理 (None)。"""
    proxy = core_config()["proxy"]["default"].strip()
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


@lru_cache(maxsize=None)
def db_config() -> Dict[str, Any]:
    """db.json (非敏感) + .env (敏感) 合并配置。

    .env 敏感字段: IB_POSTGRES_DSN, IB_REDIS_PASSWORD
    """
    data = _load("db")

    # ── 敏感字段: 仅从 .env 读取 ──
    data["postgres"]["dsn"] = _env_required("IB_POSTGRES_DSN")
    redis_password = os.environ.get("IB_REDIS_PASSWORD", "")
    if redis_password:
        data["redis"]["password"] = redis_password

    # ── 必填校验 ──
    _require(data, "postgres.pool_size", "db.json")
    _require(data, "postgres.max_overflow", "db.json")
    _require(data, "redis.host", "db.json")
    _require(data, "redis.port", "db.json")
    _require(data, "redis.db", "db.json")
    return data


@lru_cache(maxsize=None)
def llm_config() -> Dict[str, Any]:
    """LLM.json (非敏感) + .env (敏感) 合并配置。

    .env 敏感字段: IB_LLM_BASE_URL, IB_LLM_API_KEY, IB_LLM_MODEL_ID

    仅由 sync.py 读取注入 PG (system_settings key="llm"); 应用实现一律
    只读 PG, 不直接读此文件。
    """
    data = _load("LLM")

    # ── 敏感字段: 仅从 .env 读取 ──
    data["base_url"] = _env_required("IB_LLM_BASE_URL")
    data["api_key"] = _env_required("IB_LLM_API_KEY")
    data["model_id"] = _env_required("IB_LLM_MODEL_ID")

    # ── 必填校验 (非敏感) ──
    for key in (
        "timeout_s",
        "retry.attempts",
        "operators.classify.categories",
    ):
        _require(data, key, "LLM.json")
    return data
