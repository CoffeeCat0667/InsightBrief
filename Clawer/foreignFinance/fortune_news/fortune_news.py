# -*- coding: utf-8 -*-
# description: 采集 Fortune 新闻详情 (通用解析基类薄子类)
from Core.generic import GenericArticleCrawler


class FortuneNewsCrawler(GenericArticleCrawler):
    """Fortune 新闻详情爬虫。"""

    base_url = "https://fortune.com"
    content_xpath = ""
