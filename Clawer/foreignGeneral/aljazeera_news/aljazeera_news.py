# -*- coding: utf-8 -*-
# description: 采集 Al Jazeera 新闻详情 (通用解析基类薄子类)
from Core.generic import GenericArticleCrawler


class AlJazeeraNewsCrawler(GenericArticleCrawler):
    """Al Jazeera 新闻详情爬虫。"""

    base_url = "https://www.aljazeera.com"
    content_xpath = ""
