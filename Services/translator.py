# -*- coding: utf-8 -*-
"""翻译服务: 外文新闻转中文 (deep-translator / Google 免费接口)。

复用项目代理配置, 翻译接口在国内网络亦可直接使用。
"""
from __future__ import annotations

import logging
import re

from Config.config import get_proxy_config, services_config

logger = logging.getLogger(__name__)

_TRANSLATOR_CFG = services_config()["translator"]

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uF900-\uFAFF]")


def is_chinese(text: str) -> bool:
    """文本是否含中文 (含任一 CJK 扩展字符即视为中文)。"""
    return bool(_CJK_RE.search(text or ""))


def _chunk_paragraphs(text: str, size: int) -> list[str]:
    """按段落累积切块, 避免单次请求文本过长被限流。"""
    paragraphs = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(para) > size:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(para)
        elif len(current) + len(para) > size and current:
            chunks.append(current)
            current = para
        else:
            current = f"{current}\n{para}".strip() if current else para
    if current:
        chunks.append(current)
    return chunks


class Translator:
    """延迟加载 deep_translator, 目标语言固定为简体中文 (配置可调)。"""

    def __init__(self, chunk_size: int = _TRANSLATOR_CFG["chunk_size"]):
        self._client = None
        self._chunk_size = chunk_size

    def _get_client(self):
        if self._client is None:
            from deep_translator import GoogleTranslator

            self._client = GoogleTranslator(
                source=_TRANSLATOR_CFG["source"],
                target=_TRANSLATOR_CFG["target"],
                proxies=get_proxy_config(),
            )
        return self._client

    def translate(self, text: str) -> str:
        """将文本翻译为简体中文; 失败时记录告警并返回原文。"""
        text = (text or "").strip()
        if not text:
            return text
        try:
            client = self._get_client()
            if len(text) <= self._chunk_size:
                return client.translate(text)
            return "\n\n".join(
                client.translate(chunk)
                for chunk in _chunk_paragraphs(text, self._chunk_size)
            )
        except Exception as exc:  # 网络/限流等: 失败降级为原文
            logger.warning("翻译失败, 显示原文: %s", exc)
            return text