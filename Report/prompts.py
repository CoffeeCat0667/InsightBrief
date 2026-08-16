# -*- coding: utf-8 -*-
"""简报 prompt 集中管理 + LLM JSON 输出容错解析。

所有 LLM 调用约定: 输出纯 JSON (system prompt 强约束), 解析走
extract_json 容错 (剥离 code fence / 定位首 JSON 对象)。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from .llm import LLMServiceError
from .llm.base import ChatMessage

CATEGORIES_DEFAULT = ["政治", "经济", "文化", "科技"]

_SYSTEM_CLASSIFY = (
    "你是专业的新闻分类引擎。将每条新闻归入以下类别之一: {categories}。"
    "无法明确归入任何类别的输出\"其他\"。只输出 JSON, 不输出任何其它文字。"
)

_SYSTEM_SUMMARIZE = (
    "你是中文新闻摘要专家。用一句话 (不超过50字) 概括新闻的核心事实, "
    "输出简体中文。只输出 JSON, 不输出任何其它文字。"
)

_SYSTEM_TRANSLATE_TITLE = (
    "你是新闻标题翻译专家。将标题翻译成简体中文 (保留人名/机构名惯译)。"
    "只输出 JSON, 不输出任何其它文字。"
)

_SYSTEM_OVERVIEW = (
    "你是中文新闻综述编辑。根据同一类别的若干新闻条目撰写: 一个综述标题"
    " (不超过20字) 和一段综述正文 (150-250字, 归纳要点、点出趋势)。"
    "只输出 JSON, 不输出任何其它文字。"
)


def _crop(text: str, limit: int = 800) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


# ---------------------------------------------------------------- prompts

def classify_messages(items: List[Dict[str, Any]], categories: List[str]) -> List[ChatMessage]:
    """批分类: items 为 [{"idx": int, "title": str, "text": str}], 返回 JSON 列表。"""
    lines = []
    for it in items:
        lines.append(f"#{it['idx']} 标题: {_crop(it['title'], 200)}")
        lines.append(f"内容: {_crop(it['text'], 600)}")
    user = (
        "请对下列新闻逐条分类:\n" + "\n".join(lines)
        + "\n\n输出格式: {\"articles\": [{\"idx\": <编号>, \"category\": \"<类别>\"}, ...]}"
        " — 必须覆盖全部编号。"
    )
    return [
        ChatMessage("system", _SYSTEM_CLASSIFY.format(categories="、".join(categories))),
        ChatMessage("user", user),
    ]


def summarize_messages(title: str, text: str) -> List[ChatMessage]:
    user = f"标题: {_crop(title, 200)}\n正文: {_crop(text, 2000)}\n\n输出格式: {{\"summary\": \"<一句话摘要>\"}}"
    return [ChatMessage("system", _SYSTEM_SUMMARIZE), ChatMessage("user", user)]


def translate_title_messages(title: str) -> List[ChatMessage]:
    user = f"标题: {_crop(title, 300)}\n\n输出格式: {{\"title_cn\": \"<简体中文标题>\"}}"
    return [ChatMessage("system", _SYSTEM_TRANSLATE_TITLE), ChatMessage("user", user)]


def overview_messages(category: str, items: List[Dict[str, Any]]) -> List[ChatMessage]:
    lines = []
    for it in items:
        lines.append(
            f"- 标题: {_crop(it.get('title_cn') or it.get('title'), 150)}"
            f"\n  摘要: {_crop(it.get('summary') or '', 200)}"
        )
    user = (
        f"类别: {category}\n条目:\n" + "\n".join(lines)
        + "\n\n输出格式: {\"title\": \"<综述标题>\", \"overview\": \"<综述正文>\"}"
    )
    return [ChatMessage("system", _SYSTEM_OVERVIEW), ChatMessage("user", user)]


# ---------------------------------------------------------------- parsing

_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def extract_json(raw: str) -> Any:
    """容错解析 LLM 输出: 去 fence → 直解 → 正则定位首个 JSON 对象。"""
    text = (raw or "").strip()
    if text:
        try:
            return json.loads(text)
        except ValueError:
            pass
    m = _CODE_FENCE_RE.search(text or "")
    if m:
        try:
            return json.loads(m.group(1).strip())
        except ValueError:
            pass
    for candidate in re.findall(r"[{\[].*?[}\]]", text or "", re.S):
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    raise LLMServiceError(
        "LLM 输出无法解析为 JSON", kind="bad_response", detail=(raw or "")[:300]
    )


def parse_classify(raw: str, valid: List[str]) -> Dict[int, str]:
    """解析批分类结果 -> {idx: category}; 非法类别归一为 '其他'。"""
    data = extract_json(raw)
    if not isinstance(data, dict) or not isinstance(data.get("articles"), list):
        raise LLMServiceError(
            "分类输出结构非法", kind="bad_response", detail=str(data)[:300]
        )
    result: Dict[int, str] = {}
    for entry in data["articles"]:
        if not isinstance(entry, dict):
            continue
        idx = entry.get("idx")
        cat = str(entry.get("category") or "").strip()
        result[int(idx)] = cat if cat in valid else "其他"
    return result


def parse_summary(raw: str) -> str:
    data = extract_json(raw)
    if isinstance(data, dict) and data.get("summary"):
        return str(data["summary"]).strip()
    raise LLMServiceError("摘要输出结构非法", kind="bad_response", detail=str(data)[:300])


def parse_title_cn(raw: str) -> str:
    data = extract_json(raw)
    if isinstance(data, dict) and data.get("title_cn"):
        return str(data["title_cn"]).strip()
    raise LLMServiceError("标题翻译输出结构非法", kind="bad_response", detail=str(data)[:300])


def parse_overview(raw: str):
    data = extract_json(raw)
    if not isinstance(data, dict) or not data.get("title") or not data.get("overview"):
        raise LLMServiceError(
            "综述输出结构非法", kind="bad_response", detail=str(data)[:300]
        )
    return str(data["title"]).strip(), str(data["overview"]).strip()