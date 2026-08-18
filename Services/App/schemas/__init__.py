# -*- coding: utf-8 -*-
"""API 契约 (pydantic Schema) 汇总导出。"""
from .common import (
    ERROR_HTTP_STATUS,
    ApiError,
    ApiResponse,
    ErrorCode,
    Page,
    PageParams,
    fail,
    ok,
)
from .article import (
    ArticleCategory,
    ArticleContenItem,
    ArticleDetail,
    ArticleListParams,
    ArticleListItem,
    ArticleSearchParams,
    PlatformRead,
)
from .audit_log import AuditLogRead
from .auth import (
    LoginRequest,
    RegisterRequest,
    RoleRead,
    TokenResponse,
    UserRead,
)
from .brief import (
    BriefItemRead,
    BriefListParams,
    BriefRead,
    BriefTaskCreate,
    BriefTaskRead,
)
from .source import SourceCreate, SourceKind, SourceRead, SourceUpdate
from .task import (
    CrawlRunRead,
    CrawlTaskCreate,
    CrawlTaskRead,
    TaskCancelRead,
    TaskCancelRequest,
    TaskStatus,
)

__all__ = [
    "ERROR_HTTP_STATUS",
    "ApiError",
    "ApiResponse",
    "ArticleCategory",
    "ArticleContenItem",
    "ArticleDetail",
    "ArticleListParams",
    "ArticleListItem",
    "ArticleSearchParams",
    "AuditLogRead",
    "BriefItemRead",
    "BriefListParams",
    "BriefRead",
    "BriefTaskCreate",
    "BriefTaskRead",
    "CrawlRunRead",
    "CrawlTaskCreate",
    "CrawlTaskRead",
    "ErrorCode",
    "LoginRequest",
    "Page",
    "PageParams",
    "PlatformRead",
    "RegisterRequest",
    "RoleRead",
    "SourceCreate",
    "SourceKind",
    "SourceRead",
    "SourceUpdate",
    "TaskCancelRead",
    "TaskCancelRequest",
    "TaskStatus",
    "TokenResponse",
    "UserRead",
    "fail",
    "ok",
]