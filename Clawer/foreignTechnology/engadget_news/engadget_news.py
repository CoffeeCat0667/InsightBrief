# -*- coding: utf-8 -*-
# description: 采集 Engadget 新闻详情 (通用解析基类薄子类)
from Core.generic import GenericArticleCrawler


class EngadgetCrawler(GenericArticleCrawler):
    """Engadget 新闻详情爬虫。"""

    base_url = "https://www.engadget.com"
    content_xpath = '//div[contains(@class, "article-content")]'
