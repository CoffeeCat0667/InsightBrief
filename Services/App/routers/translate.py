# -*- coding: utf-8 -*-
"""临时翻译端点: 外文文章预览翻译 (结果不落库)。

供前端文章详情"翻译"按钮使用; 翻译为临时展示, PG 中文章仍存原文。
失败判定: Translator 降级返回原文, 以结果是否含中文 (is_chinese) 判失败。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..schemas import ok
from ..security import get_current_user

router = APIRouter(prefix="/api/translate", tags=["translate"])


class TranslateRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=200_000)
    title: Optional[str] = Field(default=None, max_length=2000)


@router.post("")
def translate_text(
    body: TranslateRequest,
    _=Depends(get_current_user),
):
    """翻译一段文本为简体中文 (不落库); 标题可一并翻译。"""
    from Services.translator import Translator, is_chinese

    text = body.text.strip()
    if not text:
        raise HTTPException(
            status_code=422,
            detail={"code": "validation_error", "message": "text 为空"},
        )
    translator = Translator()
    translated = translator.translate(text)
    translated_title = (
        translator.translate(body.title.strip()) if body.title and body.title.strip() else None
    )
    if not is_chinese(translated):
        raise HTTPException(
            status_code=502,
            detail={"code": "upstream_error", "message": "翻译失败, 请稍后重试"},
        )
    return ok(
        {
            "translated": translated,
            "translated_title": translated_title,
        }
    )
