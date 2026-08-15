# -*- coding: utf-8 -*-
# description: 采集 The Verge 新闻详情 (CSR 站点, 使用浏览器渲染)
from Core.fetchers import PlaywrightFetcher
from Core.generic import GenericArticleCrawler


class TheVergeCrawler(GenericArticleCrawler):
    """The Verge 新闻详情爬虫。"""

    fetch_strategy = PlaywrightFetcher
    base_url = "https://www.theverge.com"
    content_xpath = '//div[contains(@class, "duet--article--article-body")]'
