# -*- coding: utf-8 -*-
"""统一响应/错误契约 + 分页泛型。

所有 API 响应统一为 {success, data, error}; 错误携带机读码 + 可读消息。
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field, computed_field

T = TypeVar("T")


class ErrorCode(str, Enum):
    """机读错误码 (HTTP 状态码给出层级, code 给出语义)。"""

    BAD_REQUEST = "bad_request"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    VALIDATION_ERROR = "validation_error"
    RATE_LIMITED = "rate_limited"
    INTERNAL_ERROR = "internal_error"
    UPSTREAM_ERROR = "upstream_error"


# 错误码 -> HTTP 状态 (供后续路由/异常处理器统一映射)
ERROR_HTTP_STATUS = {
    ErrorCode.BAD_REQUEST: 400,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.UPSTREAM_ERROR: 502,
}


class ApiError(BaseModel):
    """错误体: code 机读, message 人读, detail 可选补充。"""

    code: ErrorCode
    message: str
    detail: Optional[Any] = None


class ApiResponse(BaseModel, Generic[T]):
    """统一响应包装: 成功时 data 非空且 error 为空, 失败反之。"""

    success: bool
    data: Optional[T] = None
    error: Optional[ApiError] = None


class PageParams(BaseModel):
    """分页查询参数 (Query 注入用)。"""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class Page(BaseModel, Generic[T]):
    """分页数据载体。"""

    items: List[T]
    total: int
    page: int
    page_size: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def pages(self) -> int:
        if self.total == 0:
            return 0
        return (self.total + self.page_size - 1) // self.page_size


def ok(data: T) -> ApiResponse[T]:
    """成功响应快捷构造。"""
    return ApiResponse(success=True, data=data)


def fail(code: ErrorCode, message: str, detail: Any = None) -> ApiResponse:
    """失败响应快捷构造。"""
    return ApiResponse(success=False, error=ApiError(code=code, message=message, detail=detail))