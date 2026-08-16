# -*- coding: utf-8 -*-
"""简报系统 (Report) — 唯一业务领地。

对 Services.App 只暴露两个入口:
- get_llm_provider(): LLM 提供方工厂 (读 PG system_settings key="llm")
- brief_processor: BriefProcessor 实例 (供 task_manager.dispatch 使用)
"""
from __future__ import annotations

from .llm import get_llm_provider, LLMError, LLMServiceError, ArticleContentError
from .processor import BriefProcessor

brief_processor = BriefProcessor()

__all__ = [
    "get_llm_provider",
    "LLMError",
    "LLMServiceError",
    "ArticleContentError",
    "BriefProcessor",
    "brief_processor",
]