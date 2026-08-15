# -*- coding: utf-8 -*-
"""
Core primitives shared by all news crawler implementations.
"""

__version__ = "0.1.0"

from .base import BaseNewsCrawler
from .fetchers import (
    CurlCffiFetcher,
    FetchRequest,
    FetchStrategy,
    PlaywrightFetcher,
)
from .models import (
    DEFAULT_USER_AGENT,
    ContentItem,
    ContentType,
    NewsItem,
    NewsMetaInfo,
    RequestHeaders,
)

__all__ = [
    "BaseNewsCrawler",
    "ContentItem",
    "ContentType",
    "CurlCffiFetcher",
    "DEFAULT_USER_AGENT",
    "FetchRequest",
    "FetchStrategy",
    "PlaywrightFetcher",
    "NewsItem",
    "NewsMetaInfo",
    "RequestHeaders",
]
