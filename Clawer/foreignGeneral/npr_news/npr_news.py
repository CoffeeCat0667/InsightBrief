# -*- coding: utf-8 -*-
# description: 采集 NPR 新闻详情 (通用解析基类薄子类)
from Core.generic import GenericArticleCrawler


class NPRNewsCrawler(GenericArticleCrawler):
    """NPR 新闻详情爬虫。"""

    base_url = "https://www.npr.org"
    content_xpath = '//div[@id="storytext"]'
