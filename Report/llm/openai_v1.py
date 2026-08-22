# -*- coding: utf-8 -*-
"""OpenAI V1 统一实现 — 不区分提供商。

POST {base_url}/chat/completions, Authorization: Bearer {api_key},
model={model_id}。换厂商 = 改 LLM.json 三字段 (base_url/api_key/model_id),
代码零改动。

重试语义: 仅 LLMServiceError 按 retry.attempts 指数退避重试;
ArticleContentError (403 风控) 不重试, 直接上抛。
"""
from __future__ import annotations

import logging
import time
from typing import List, Optional

import requests

from .base import ChatMessage, LLMProvider
from .errors import ArticleContentError, LLMServiceError

logger = logging.getLogger(__name__)

_STATUS_GLOBAL = frozenset({401, 403, 429, 500, 502, 503, 504})


class OpenAI_V1Provider(LLMProvider):
    """OpenAI V1 /chat/completions 客户端 (requests, 线程安全)。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model_id: str,
        *,
        timeout_s: float = 60,
        retry_attempts: int = 3,
        backoff_s: List[float] = (1, 2, 4),
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model_id = model_id
        self._timeout = timeout_s
        self._attempts = max(1, retry_attempts)
        self._backoff = list(backoff_s or (1,))

    def chat(
        self,
        messages: List[ChatMessage],
        *,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
    ) -> str:
        last: Optional[Exception] = None
        for attempt in range(self._attempts):
            try:
                return self._chat_once(messages, temperature=temperature, max_tokens=max_tokens)
            except LLMServiceError as exc:
                last = exc
                if attempt < self._attempts - 1:
                    delay = self._backoff[min(attempt, len(self._backoff) - 1)]
                    logger.warning(
                        "LLM 服务错误 (第 %d/%d 次): %s, %.1fs 后重试",
                        attempt + 1,
                        self._attempts,
                        exc,
                        delay,
                    )
                    time.sleep(delay)
        assert last is not None
        raise last

    def _chat_once(
        self,
        messages: List[ChatMessage],
        *,
        temperature: float,
        max_tokens: Optional[int],
    ) -> str:
        payload = {
            "model": self._model_id,
            "messages": [
                {"role": m.role, "content": m.content} for m in messages
            ],
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        try:
            resp = requests.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self._timeout,
            )
        except requests.exceptions.Timeout as exc:
            raise LLMServiceError(
                f"LLM 请求超时 ({self._timeout}s)", kind="timeout", detail=str(exc)
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise LLMServiceError(
                f"LLM 连接失败: {exc}", kind="connection", detail=str(exc)
            ) from exc

        status = resp.status_code
        if status == 200:
            try:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError) as exc:
                raise LLMServiceError(
                    "LLM 响应格式非法", kind="bad_response", detail=str(exc)
                ) from exc

        try:
            detail = resp.json()
        except ValueError:
            detail = resp.text[:200]
        if status == 403:
            error_code = ""
            if isinstance(detail, dict):
                error_obj = detail.get("error") or detail
                error_code = str(error_obj.get("code", "")).lower()
            _CONTENT_POLICY_CODES = frozenset({
                "content_policy", "content_moderation", "sensitive",
                "content_policy_violation", "moderation",
            })
            if error_code and error_code not in _CONTENT_POLICY_CODES:
                raise LLMServiceError(
                    f"LLM 鉴权/权限失败 (403): {str(detail)[:200]}",
                    kind="http_error",
                    detail=detail,
                )
            raise ArticleContentError(
                f"内容政策限制 (403): {str(detail)[:200]}", detail=detail
            )
        if status in (401, 429) or status >= 500 or status in _STATUS_GLOBAL:
            raise LLMServiceError(
                f"LLM 返回 HTTP {status}: {str(detail)[:200]}",
                kind="rate_limited" if status == 429 else "http_error",
                detail=detail,
            )
        raise LLMServiceError(
            f"LLM 返回 HTTP {status}: {str(detail)[:200]}",
            kind="http_error",
            detail=detail,
        )