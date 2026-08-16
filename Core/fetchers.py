# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass, field
from typing import Callable, Mapping, MutableMapping, Optional, Protocol

from Config.config import core_config, get_proxy_config  # noqa: E402

logger = logging.getLogger(__name__)


@dataclass
class FetchRequest:
    """Parameters used for an HTTP fetch operation."""

    url: str
    method: str = "GET"
    headers: Mapping[str, str] | None = None
    # 超时唯一来源为平台级 fetch_timeout (base 显式传入); 此兜底仅覆盖
    # 绕过爬虫直接构造 FetchRequest 的调用路径。
    timeout: float = 30.0
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
    """执行请求: 直连失败 (异常或非 200, 如 202 反爬质询) 且配置了代理时自动用代理重试一次。

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
        if proxies is None:
            raise RuntimeError(
                f"Failed to fetch content: {getattr(response, 'status_code')}"
            )
        logger.info(
            "Direct fetch status %s, retrying via proxy %s",
            getattr(response, "status_code"),
            proxies["https"],
        )
        response = retry_with_proxies(proxies)
    status = getattr(response, "status_code")
    if status != 200:
        raise RuntimeError(f"Failed to fetch content: {status}")
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
    资源型请求 (图片/视频/字体) 会被拦截以加快页面加载。

    **线程模型**: playwright sync API 的调度 fiber 绑定创建线程, 跨线程
    调用 (即使串行) 会抛 "cannot switch to a different thread"。因此所有
    浏览器操作通过队列投递到**唯一专用线程**执行 (任务并发
    ThreadPoolExecutor(4) 下安全; 请求串行排队, 天然互斥)。
    """

    launch_timeout: float = core_config()["playwright"]["launch_timeout"]
    page_timeout: float = core_config()["playwright"]["page_timeout"]
    settle_ms: int = core_config()["playwright"]["settle_ms"]

    _pw_thread: Optional[threading.Thread] = None
    _pw_queue: Optional["queue.Queue"] = None
    _pw_start_lock = threading.Lock()

    _playwright = None
    _browser = None
    _context = None
    _context_proxies: Optional[Mapping[str, str]] = None

    @classmethod
    def _submit(cls, fn) -> object:
        """把 fn 投递到 playwright 专用线程执行并同步等待结果 (异常重抛)。"""
        cls._ensure_thread()
        result_q: queue.Queue = queue.Queue()
        cls._pw_queue.put((fn, result_q))
        ok, value = result_q.get()
        if not ok:
            raise value
        return value

    @classmethod
    def _ensure_thread(cls) -> None:
        if cls._pw_thread is not None:
            return
        with cls._pw_start_lock:
            if cls._pw_thread is not None:
                return
            cls._pw_queue = queue.Queue()
            cls._pw_thread = threading.Thread(
                target=cls._pw_loop,
                name="insightbrief-playwright",
                daemon=True,
            )
            cls._pw_thread.start()

    @classmethod
    def _pw_loop(cls) -> None:
        """专用线程主循环: 本线程内创建/操作 playwright, 永不退出。"""
        while True:
            fn, result_q = cls._pw_queue.get()
            if fn is None:
                return
            try:
                result_q.put((True, fn()))
            except BaseException as exc:  # 捕获后回传调用线程重抛, 不中断循环
                result_q.put((False, exc))

    @classmethod
    def _ensure_browser(cls, proxies: Optional[Mapping[str, str]]) -> None:
        """(仅在 playwright 专用线程内调用) 惰性启动浏览器。"""
        if cls._browser is not None and cls._context_proxies == proxies:
            return
        cls._close_browser()
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
    def _close_browser(cls) -> None:
        """(仅在 playwright 专用线程内调用) 释放浏览器资源。"""
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

    @classmethod
    def close(cls) -> None:
        """停止专用线程并释放浏览器 (幂等; 进程退出前可选调用)。"""
        if cls._pw_thread is None:
            return
        try:
            cls._submit(cls._close_browser)
        except Exception:  # 线程可能已终止, 忽略并强制清理
            pass
        with cls._pw_start_lock:
            if cls._pw_queue is not None:
                cls._pw_queue.put(None)
            cls._pw_thread = None
            cls._pw_queue = None

    def fetch(self, request: FetchRequest) -> str:
        return self._submit(lambda: self._fetch_on_pw_thread(request))

    def _fetch_on_pw_thread(self, request: FetchRequest) -> str:
        """(仅在 playwright 专用线程内调用) 单次页面抓取。"""
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