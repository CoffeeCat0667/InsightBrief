# -*- coding: utf-8 -*-
# description: 采集 Forbes 新闻详情 (通用解析基类薄子类)
from Core.generic import GenericArticleCrawler


class ForbesNewsCrawler(GenericArticleCrawler):
    """Forbes 新闻详情爬虫。"""

    base_url = "https://www.forbes.com"
    content_xpath = '//div[contains(@class, "article-body")]'
