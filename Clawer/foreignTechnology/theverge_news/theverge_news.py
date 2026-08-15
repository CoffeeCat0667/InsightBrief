# -*- coding: utf-8 -*-
# description: 采集 The Verge 新闻详情 (CSR 站点, 使用浏览器渲染)
from Core.fetchers import PlaywrightFetcher
from Config.config import platform_config
from Core.generic import GenericArticleCrawler


_CFG = platform_config("theverge")


class TheVergeCrawler(GenericArticleCrawler):
    """The Verge 新闻详情爬虫。"""

    fetch_strategy = PlaywrightFetcher
    base_url = _CFG["base_url"]
    content_xpath = _CFG.get("content_xpath", "")
