# -*- coding: utf-8 -*-
"""LLM 提供方工厂: 从 PG system_settings (key="llm") 读取配置并实例化。

配置真相流: Config/LLM.json → sync_llm_config → system_settings → 本工厂。
进程内 lru_cache 定型 (启动后配置变更不重新生效, 与现有配置模型一致)。
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Dict

from .base import LLMProvider
from .errors import LLMError, ArticleContentError, LLMServiceError  # noqa: F401 (re-export)
from .openai_v1 import OpenAI_V1Provider

logger = logging.getLogger(__name__)


@lru_cache(maxsize=None)
def get_llm_provider() -> LLMProvider:
    """从 PG 读取 LLM 配置并构造 provider (进程定型, 线程安全)。

    配置缺失/格式非法抛 LLMError — 调用方 (简报任务) 应将其视为
    "LLM 不可用" 并直接报错, 不降级。
    """
    from Services.App.db import SessionLocal
    from Services.App.models import SystemSetting

    cfg: Dict[str, Any]
    with SessionLocal() as session:
        row = session.get(SystemSetting, "llm")
        if row is None:
            raise LLMError("LLM 配置缺失 (system_settings key='llm', 请先运行 run_llm_sync)")
        cfg = row.value or {}

    for key in ("base_url", "api_key", "model_id"):
        if not cfg.get(key):
            raise LLMError(f"LLM 配置缺少必填字段: {key}")

    return OpenAI_V1Provider(
        base_url=str(cfg["base_url"]),
        api_key=str(cfg["api_key"]),
        model_id=str(cfg["model_id"]),
        timeout_s=float(cfg.get("timeout_s", 60)),
        retry_attempts=int((cfg.get("retry") or {}).get("attempts", 3)),
        backoff_s=list((cfg.get("retry") or {}).get("backoff_s", (1, 2, 4))),
    )