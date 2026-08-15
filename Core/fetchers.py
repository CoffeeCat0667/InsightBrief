# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Callable, Mapping, MutableMapping, Optional, Protocol

logger = logging.getLogger(__name__)

# 默认代理地址; 可通过环境变量 CRAWL_PROXY 覆盖, 设为空串可禁用代理 fallback
DEFAULT_PROXY = "http://127.0.0.1:7897"


def get_proxy_config() -> Optional[Mapping[str, str]]:
    """读取代理配置 (环境变量 CRAWL_PROXY, 默认 http://127.0.0.1:7897)。

    返回 {"http": proxy, "https": proxy} 供 requests/curl_cffi 使用;
    环境变量为空串时返回 None, 表示完全禁用代理。
    """
    proxy = os.environ.get("CRAWL_PROXY", DEFAULT_PROXY).strip()
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


@dataclass
class FetchRequest:
    """Parameters used for an HTTP fetch operation."""

    url: str
    method: str = "GET"
    headers: Mapping[str, str] | None = None
    timeout: float = 10.0
    allow_redirects: bool = True
    impersonate: Optional[str] = None
    params: Mapping[str, str] | None = None
    data: Mapping[str, str] | None = None
    cookies: Mapping[str, str] | None = None
    proxies: Optional[Mapping[str, str]] = None
    extras: MutableMapping[str, object] = field(default_factory=dict)


class FetchStrategy(Protocol):
    """Strategy interface for fetching raw content."""

    def fetch(self, request: FetchRequest) -> str:
        ...


def _fetch_with_fallback(
    make_request: Callable[[], object],
    retry_with_proxies: Callable[[Mapping[str, str]], object],
    expected_errors: tuple,
    proxies: Optional[Mapping[str, str]],
) -> object:
    """执行请求: 直连失败且配置了代理时自动用代理重试一次。

    Args:
        make_request: 无参调用, 返回响应对象 (初次直连)
        retry_with_proxies: 接收 proxies 字典, 返回响应对象 (代理重试)
        expected_errors: 触发重试的异常类型元组
        proxies: 代理配置; None 表示失败直接抛出
    """
    try:
        response = make_request()
    except expected_errors as exc:
        if proxies is None:
            raise
        logger.info(
            "Direct connection failed (%s), retrying via proxy %s",
            exc,
            proxies["https"],
        )
        response = retry_with_proxies(proxies)
    if getattr(response, "status_code") != 200:
        raise RuntimeError(f"Failed to fetch content: {getattr(response, 'status_code')}")
    return response


class CurlCffiFetcher(FetchStrategy):
    """Fetcher backed by curl_cffi for high-fidelity browser impersonation."""

    def fetch(self, request: FetchRequest) -> str:
        try:
            from curl_cffi import requests as curl_requests
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("curl_cffi is required for this fetcher") from exc

        kwargs = {
            "headers": request.headers,
            "timeout": request.timeout,
            "allow_redirects": request.allow_redirects,
            "params": request.params,
            "data": request.data,
            "cookies": request.cookies,
        }
        impersonate = request.impersonate or request.extras.get("impersonate")
        if impersonate:
            kwargs["impersonate"] = impersonate

        proxies = request.proxies or get_proxy_config()

        def make_request():
            return curl_requests.request(
                method=request.method,
                url=request.url,
                **kwargs,
            )

        def retry_with_proxies(proxy_map):
            return curl_requests.request(
                method=request.method,
                url=request.url,
                proxies=proxy_map,
                **kwargs,
            )

        response = _fetch_with_fallback(
            make_request,
            retry_with_proxies,
            expected_errors=curl_requests.exceptions.RequestException,
            proxies=proxies,
        )
        response.encoding = response.encoding or "utf-8"
        return response.text


class PlaywrightFetcher(FetchStrategy):
    """浏览器渲染型 fetcher: 用于 CSR (前端异步加载正文) 站点。

    复用单一 chromium 实例与 BrowserContext, 每次 fetch 只开新 page,
    等待页面完成渲染后取回真实 DOM 的 HTML, 再交给现有解析逻辑。
    资源型请求 (图片/视频/字体) 会被 拦截以加快页面加载。
    """

    launch_timeout: float = 40.0
    page_timeout: float = 40.0
    settle_ms: int = 1200

    _playwright = None
    _browser = None
    _context = None
    _context_proxies: Optional[Mapping[str, str]] = None

    @classmethod
    def _ensure_browser(cls, proxies: Optional[Mapping[str, str]]) -> None:
        if cls._browser is not None and cls._context_proxies == proxies:
            return
        cls.close()
        from playwright.sync_api import sync_playwright  # 按需加载, 不污染冷启动

        cls._playwright = sync_playwright().start()
        kwargs: dict = {}
        if proxies:
            kwargs["proxy"] = {"server": proxies.get("https") or proxies.get("http")}
        try:
            cls._browser = cls._playwright.chromium.launch(**kwargs)
        except Exception:
            # 首次使用可能缺浏览器内核 (python -m playwright install chromium)
            cls._playwright.stop()
            cls._playwright = None
            raise RuntimeError(
                "Playwright 浏览器内核未安装, 请先执行: python -m playwright install chromium"
            )
        cls._context = cls._browser.new_context(ignore_https_errors=True)
        cls._context_proxies = proxies

    @classmethod
    def close(cls) -> None:
        """释放浏览器资源 (进程退出前可选调用)。"""
        if cls._playwright is None:
            return
        try:
            if cls._context is not None:
                cls._context.close()
        finally:
            try:
                cls._browser.close()
            finally:
                cls._playwright.stop()
                cls._playwright = None
                cls._browser = None
                cls._context = None
                cls._context_proxies = None

    def fetch(self, request: FetchRequest) -> str:
        proxies = request.proxies or get_proxy_config()
        self._ensure_browser(proxies)
        assert self._playwright and self._context  # pragma: no cover - guard for type checkers
        page = self._context.new_page()
        try:
            if request.headers and request.headers.get("User-Agent"):
                page.set_extra_http_headers(
                    {"User-Agent": str(request.headers["User-Agent"])}
                )
            try:
                def _abort_non_document(route) -> None:
                    if route.request.resource_type in (
                        "image", "media", "font", "stylesheet"
                    ):
                        route.abort()
                    else:
                        route.continue_()

                page.route("**/*", _abort_non_document)
            except Exception:  # pragma: no cover - route 失败不影响主流程
                pass
            try:
                page.goto(
                    request.url,
                    wait_until="domcontentloaded",
                    timeout=int(self.page_timeout * 1000),
                )
                page.wait_for_timeout(self.settle_ms)
            except Exception:  # 超时/跳转异常可能仍已渲染, 继续取 DOM
                pass
            return page.content()
        finally:
            page.close()