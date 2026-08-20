# -*- coding: utf-8 -*-
"""InsightBrief Web API 入口: FastAPI 实例、lifespan 引导、统一响应/错误契约。

启动: uvicorn Services.App.main:app --host 127.0.0.1 --port 8000
lifespan: 建表兜底 + 配置->DB 源同步 + 角色/管理员种子 + 任务运行时接线。
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles as StarletteStaticFiles

from .db import SessionLocal
from .admin_settings import sync_registration_default
from .routers import admin, articles, audit_logs, auth, briefs, schedules, sources, tasks, translate
from .schemas import ERROR_HTTP_STATUS, ApiError, ErrorCode, fail
from .security import seed_all
from .sync import ensure_schema, run_llm_sync, run_sources_sync
from .task_manager import manager
from .schedule_manager import schedule_manager
from .auto_brief import auto_brief_manager

logger = logging.getLogger(__name__)

_lifespan_done = False


def _bootstrap() -> None:
    """启动引导: 建表兜底 + 源同步 + 角色/管理员种子 (幂等)。"""
    global _lifespan_done
    if _lifespan_done:
        return
    ensure_schema()
    run_sources_sync()
    run_llm_sync()
    with SessionLocal() as session:
        seed_all(session)
        sync_registration_default(session)
    _lifespan_done = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    _bootstrap()
    manager.recover_stale_tasks()
    manager.recover_stale_brief_tasks()
    manager.set_loop(asyncio.get_running_loop())
    auto_brief_manager.recover()
    schedule_manager.start()
    yield
    schedule_manager.shutdown()
    manager.shutdown()


# 生产环境用 IB_DISABLE_DOCS=1 关闭交互文档 (仅暴露业务 API)
_docs_enabled = os.environ.get("IB_DISABLE_DOCS", "").lower() not in {"1", "true", "yes"}

app = FastAPI(
    title="InsightBrief API",
    version="0.2.0",
    description="新闻抓取/翻译/简报 Web 后端",
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发期全放行; 生产按前端域名收紧
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _as_error(detail) -> ApiError:
    """把路由抛出的 detail 规范化为 ApiError (支持 dict 或原始消息)。"""
    if isinstance(detail, dict) and "code" in detail:
        return ApiError(
            code=ErrorCode(detail["code"]),
            message=str(detail.get("message", "")),
            detail=detail.get("detail"),
        )
    return ApiError(code=ErrorCode.INTERNAL_ERROR, message=str(detail))


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    error = _as_error(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content=fail(
            error.code,
            error.message or ERROR_HTTP_STATUS.get(error.code, "http error"),
            error.detail,
        ).model_dump(mode="json"),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content=fail(ErrorCode.VALIDATION_ERROR, "请求参数校验失败", exc.errors()).model_dump(mode="json"),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=fail(ErrorCode.INTERNAL_ERROR, "服务器内部错误").model_dump(mode="json"),
    )


@app.get("/api/health", tags=["system"])
def health():
    """健康检查 (lifespan 已引导则 ready)。"""
    return {"success": True, "data": {"status": "ok", "version": app.version}}


app.include_router(auth.router)
app.include_router(sources.router)
app.include_router(admin.router)
app.include_router(articles.router)
app.include_router(articles.platforms_router)
app.include_router(tasks.router)
app.include_router(tasks.events_router)
app.include_router(schedules.router)
app.include_router(briefs.router)
app.include_router(briefs.briefs_router)
app.include_router(audit_logs.router)
app.include_router(translate.router)

# 前端静态资源 (Client/ 单页应用; 挂载在 API 路由之后, 不遮挡 /api 与 /docs)
# no-cache: SPA 迭代频繁, 防浏览器命中旧 JS/CSS 导致"修了没生效"假象
_client_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "Client")
if os.path.isdir(_client_dir):

    class _NoCacheStaticFiles(StaticFiles):
        async def get_response(self, path, scope):
            response = await super().get_response(path, scope)
            response.headers["Cache-Control"] = "no-cache"
            return response

    class _SpaStaticFiles(_NoCacheStaticFiles):
        """SPA fallback: 非 /api 路径未命中静态文件时回退 index.html。"""

        async def get_response(self, path, scope):
            try:
                return await super().get_response(path, scope)
            except StarletteHTTPException as exc:
                root_path = scope.get("root_path", "")
                full = path.replace("\\", "/")
                if root_path:
                    full = root_path.lstrip("/") + "/" + full
                if exc.status_code == 404 and not full.startswith("api/"):
                    return await super().get_response("index.html", scope)
                raise

    app.mount("/", _SpaStaticFiles(directory=_client_dir, html=True), name="static")