# -*- coding: utf-8 -*-
"""管理面板设置读写: 注册开关 / 非管理员可见选项卡 / LLM 配置同步。"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from Config.config import CONFIG_DIR, llm_config
from .models import SystemSetting

logger = logging.getLogger(__name__)

_REGISTRATION_KEY = "registration"
_TABS_KEY = "non_admin_tabs"
_LLM_KEY = "llm"

ALL_TABS = ("articles", "brief", "crawl", "sources")
DEFAULT_NON_ADMIN_TABS = ("articles", "brief")


class LLMProbeError(RuntimeError):
    """LLM 连通性检查失败。"""


def _get_setting(session: Session, key: str) -> Optional[dict]:
    row = session.get(SystemSetting, key)
    return row.value if row is not None else None


def _set_setting(session: Session, key: str, value: dict, description: str = "") -> None:
    row = session.get(SystemSetting, key)
    if row is None:
        session.add(SystemSetting(key=key, value=value, description=description or key))
    else:
        row.value = value
    session.commit()


# ---------------------------------------------------------------- 注册开关
def get_registration_enabled(session: Session) -> bool:
    value = _get_setting(session, _REGISTRATION_KEY)
    return bool((value or {}).get("enabled", True))


def set_registration_enabled(session: Session, enabled: bool) -> bool:
    _set_setting(
        session, _REGISTRATION_KEY, {"enabled": bool(enabled)}, "是否允许公开注册"
    )
    return bool(enabled)


# ---------------------------------------------------------------- 选项卡
def get_non_admin_tabs(session: Session) -> List[str]:
    value = _get_setting(session, _TABS_KEY)
    tabs = (value or {}).get("tabs")
    if tabs is None:
        return list(DEFAULT_NON_ADMIN_TABS)
    return [tab for tab in tabs if tab in ALL_TABS] or list(DEFAULT_NON_ADMIN_TABS)


def set_non_admin_tabs(session: Session, tabs: List[str]) -> List[str]:
    cleaned = [tab for tab in tabs if tab in ALL_TABS]
    _set_setting(session, _TABS_KEY, {"tabs": cleaned}, "非管理员可见选项卡")
    return cleaned


# ---------------------------------------------------------------- LLM 配置
def current_llm_fields() -> Dict[str, str]:
    cfg = llm_config()
    return {
        "base_url": cfg.get("base_url", ""),
        "api_key": cfg.get("api_key", ""),
        "model_id": cfg.get("model_id", ""),
    }


def _llm_file_path() -> Path:
    return CONFIG_DIR / "LLM.json"


def _probe_once(base_url: str, api_key: str, model_id: str, timeout: float = 15.0) -> None:
    url = f"{base_url.rstrip('/')}/chat/completions"
    try:
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model_id,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
            timeout=timeout,
        )
    except requests.exceptions.Timeout as exc:
        raise LLMProbeError(f"连接超时 ({timeout}s): {exc}") from exc
    except requests.exceptions.RequestException as exc:
        raise LLMProbeError(f"连接失败: {exc}") from exc
    if resp.status_code == 200:
        return
    try:
        detail = resp.json()
    except ValueError:
        detail = resp.text[:200]
    raise LLMProbeError(f"LLM 返回 HTTP {resp.status_code}: {str(detail)[:200]}")


def probe_llm(base_url: str, api_key: str, model_id: str) -> None:
    """连通性检查: 成功返回 None, 失败抛 LLMProbeError。"""
    if not base_url or not api_key or not model_id:
        raise LLMProbeError("base_url / api_key / model_id 均不能为空")
    _probe_once(base_url, api_key, model_id)


def write_llm_fields(session: Session, *, base_url: str, api_key: str, model_id: str) -> Dict[str, str]:
    """连通性检查通过后, 同时写 LLM.json 与 PG system_settings。"""
    path = _llm_file_path()
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["base_url"] = base_url
    cfg["api_key"] = api_key
    cfg["model_id"] = model_id
    path.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _set_setting(
        session,
        _LLM_KEY,
        cfg,
        "LLM 配置 (OpenAI V1 统一接口), 来源 Config/LLM.json",
    )
    llm_config.cache_clear()
    try:
        from Report.llm import get_llm_provider

        get_llm_provider.cache_clear()
    except Exception:
        logger.warning("无法清理 LLM provider 缓存", exc_info=True)
    return {
        "base_url": cfg["base_url"],
        "api_key": cfg["api_key"],
        "model_id": cfg["model_id"],
    }


def sync_registration_default(session: Session) -> None:
    """启动引导: 无注册设置记录时写入默认开启。"""
    if _get_setting(session, _REGISTRATION_KEY) is None:
        _set_setting(session, _REGISTRATION_KEY, {"enabled": True}, "是否允许公开注册")
