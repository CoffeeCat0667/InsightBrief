# -*- coding: utf-8 -*-
"""LLM 错误分类 — 全挂判定的依据。

两类错误语义 (方案 v5):
- LLMServiceError: 服务级嫌疑 (连接失败/超时/401/5xx/429 重试耗尽) —
  计入"连续失败"全挂判定
- ArticleContentError: 内容风控 (403/内容审核) — 服务正常, 单篇被拒,
  **不**计入全挂判定, 该文降级翻译兜底
"""
from __future__ import annotations

from typing import Any, Optional


class LLMError(Exception):
    """LLM 调用错误基类。"""

    def __init__(
        self,
        message: str,
        *,
        kind: str = "llm_error",
        detail: Optional[Any] = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.detail = detail


class LLMServiceError(LLMError):
    """服务不可用类错误: 连接/超时/鉴权/限流/服务器错误 (重试耗尽后抛出)。"""

    def __init__(self, message: str, *, kind: str = "service", detail: Any = None) -> None:
        super().__init__(message, kind=kind, detail=detail)


class ArticleContentError(LLMError):
    """内容政策类错误 (403/内容审核): 单篇被拒, 不视为服务故障。"""

    def __init__(self, message: str, *, kind: str = "content_policy", detail: Any = None) -> None:
        super().__init__(message, kind=kind, detail=detail)