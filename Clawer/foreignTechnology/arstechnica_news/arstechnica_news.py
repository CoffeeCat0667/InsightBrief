# -*- coding: utf-8 -*-
# description: 采集 Ars Technica 新闻详情 (通用解析基类薄子类)
from Core.generic import GenericArticleCrawler


class ArsTechnicaCrawler(GenericArticleCrawler):
    """Ars Technica 新闻详情爬虫。"""

    base_url = "https://arstechnica.com"
    content_xpath = '//div[@id="article-guts"]'
