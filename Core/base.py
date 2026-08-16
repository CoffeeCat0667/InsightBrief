# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Type

from tenacity import Retrying, stop_after_attempt, wait_fixed

from Config.config import core_config, get_proxy_config, platform_config
from .fetchers import (
    CurlCffiFetcher,
    FetchRequest,
    FetchStrategy,
)
from .models import ContentItem, NewsItem, NewsMetaInfo, RequestHeaders

_FETCH = core_config()["fetch"]
_SAVE_DIR = core_config()["paths"]["save_dir"]


class BaseNewsCrawler(ABC):
    """
    Template for news crawlers.

    Subclasses implement platform-specific parsing while reusing the shared
    fetching, validation, and persistence logic.
    """

    headers_model: Type[RequestHeaders] = RequestHeaders
    fetch_strategy: Type[FetchStrategy] = CurlCffiFetcher
    fetch_attempts: int = _FETCH["attempts"]
    fetch_wait_seconds: float = _FETCH["wait_seconds"]
    fetch_timeout: float = _FETCH["timeout"]
    persist_by_default: bool = True

    def __init__(
        self,
        new_url: str,
        save_path: str = _SAVE_DIR,
        headers: Optional[RequestHeaders] = None,
        fetcher: Optional[FetchStrategy] = None,
        platform_id: Optional[str] = None,
    ):
        self.new_url = new_url
        self.url = new_url  # Compatibility with legacy usages
        self.save_path = Path(save_path)
        self.platform_id = platform_id
        self.headers_model_instance = headers or self.headers_model()
        self.headers = self.headers_model_instance.to_http_headers()
        self.fetcher = fetcher or self.create_fetcher()
        self.logger = logging.getLogger(self.__class__.__name__)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
                )
            )
            self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)

    # ---------------------------------------------------------------------- #
    # Fetching
    # ---------------------------------------------------------------------- #
    def create_fetcher(self) -> FetchStrategy:
        """Instantiate the fetch strategy used for this crawler."""
        return self.fetch_strategy()

    def build_fetch_request(self) -> FetchRequest:
        """Produce the request parameters for the fetcher."""
        timeout = self.fetch_timeout
        if self.platform_id:
            timeout = (
                platform_config(self.platform_id).get("fetch_timeout") or timeout
            )
        return FetchRequest(
            url=self.new_url,
            headers=self.headers,
            timeout=timeout,
        )

    def fetch_content(self) -> str:
        """Fetch remote HTML with retry semantics."""
        request = self.build_fetch_request()
        # 统一注入代理配置: 直连失败时 fetcher 内部会自动用代理重试
        if request.proxies is None:
            request.proxies = get_proxy_config()
        retryer = Retrying(
            stop=stop_after_attempt(self.fetch_attempts),
            wait=wait_fixed(self.fetch_wait_seconds),
            reraise=True,
        )
        return retryer(self._fetch_once, request)

    def _fetch_once(self, request: FetchRequest) -> str:
        self.logger.info("Start to fetch content from %s", request.url)
        return self.fetcher.fetch(request)

    # ---------------------------------------------------------------------- #
    # Parsing
    # ---------------------------------------------------------------------- #
    @abstractmethod
    def parse_content(self, html: str) -> NewsItem:
        """Convert raw HTML into a NewsItem."""

    # ---------------------------------------------------------------------- #
    # Validation & persistence
    # ---------------------------------------------------------------------- #
    def validate_item(self, news_item: NewsItem) -> None:
        """Ensure crawled content is non-empty."""
        if not news_item.contents and not news_item.texts:
            raise ValueError(f"Empty content for article: {news_item.title}")

    def save_as_json(self, news_item: NewsItem) -> Path:
        """Persist the NewsItem as JSON."""
        self.save_path.mkdir(parents=True, exist_ok=True)
        path = self.save_path / f"{self.get_article_id()}.json"
        path.write_text(
            json.dumps(news_item.to_dict(), ensure_ascii=False, indent=4),
            encoding="utf-8",
        )
        return path

    def run(self, persist: Optional[bool] = None) -> NewsItem:
        """Full crawling pipeline."""
        should_persist = self.persist_by_default if persist is None else persist
        html = self.fetch_content()
        news_item = self.parse_content(html)
        self.validate_item(news_item)
        if should_persist:
            self.save_as_json(news_item)
        self.logger.info("Success to get content from %s", self.new_url)
        return news_item

    # ---------------------------------------------------------------------- #
    # Helpers
    # ---------------------------------------------------------------------- #
    @abstractmethod
    def get_article_id(self) -> str:
        """Return the unique identifier used for persistence."""

    def get_save_json_path(self) -> str:
        """Compute the output path for the JSON artifact."""
        return str(self.save_path / f"{self.get_article_id()}.json")

    def compose_news_item(
        self,
        *,
        title: str,
        meta_info: NewsMetaInfo,
        contents: list[ContentItem],
        subtitle: Optional[str] = None,
        news_id: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> NewsItem:
        """Utility for composing a NewsItem with derived fields."""
        return NewsItem(
            title=title,
            subtitle=subtitle,
            news_url=self.new_url,
            news_id=news_id or self.get_article_id(),
            meta_info=meta_info,
            contents=contents,
            extra=extra or {},
        )
