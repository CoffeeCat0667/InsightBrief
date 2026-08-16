# -*- coding: utf-8 -*-
"""LLM 提供方抽象: 单一 chat() 契约, 换供应商只换实现不换调用方。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class ChatMessage:
    """一次 LLM 对话消息 (OpenAI V1 /chat/completions 同构)。"""

    role: str  # "system" | "user" | "assistant"
    content: str


class LLMProvider(ABC):
    """LLM 提供方接口 (唯一业务契约)。

    实现须自行处理: 超时、重试 (仅 LLMServiceError, 指数退避)、错误分类
    (LLMServiceError vs ArticleContentError)。
    """

    @abstractmethod
    def chat(
        self,
        messages: List[ChatMessage],
        *,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
    ) -> str:
        """发送对话, 返回助手文本 (失败抛 LLMServiceError / ArticleContentError)。"""
        raise NotImplementedError