# -*- coding: utf-8 -*-
# description: 采集 WIRED 新闻详情 (通用解析基类薄子类)
from Core.generic import GenericArticleCrawler


class WiredNewsCrawler(GenericArticleCrawler):
    """WIRED 新闻详情爬虫。"""

    base_url = "https://www.wired.com"
    content_xpath = '//div[contains(@class, "body__inner-container")]'
