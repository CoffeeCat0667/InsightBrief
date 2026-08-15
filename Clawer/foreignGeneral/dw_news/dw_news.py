# -*- coding: utf-8 -*-
# description: 采集 Deutsche Welle 新闻详情 (通用解析基类薄子类)
from Core.generic import GenericArticleCrawler


class DWNewsCrawler(GenericArticleCrawler):
    """Deutsche Welle 新闻详情爬虫。"""

    base_url = "https://www.dw.com"
    content_xpath = ""
