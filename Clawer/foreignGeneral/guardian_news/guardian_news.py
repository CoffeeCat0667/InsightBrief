# -*- coding: utf-8 -*-
# description: 采集 The Guardian 新闻详情 (通用解析基类薄子类)
from Core.generic import GenericArticleCrawler


class GuardianNewsCrawler(GenericArticleCrawler):
    """The Guardian 新闻详情爬虫。"""

    base_url = "https://www.theguardian.com"
    content_xpath = '//div[@data-gu-name="body"]'
