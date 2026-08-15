# -*- coding: utf-8 -*-
# description: 采集 ZDNet 新闻详情 (通用解析基类薄子类)
from Core.generic import GenericArticleCrawler


class ZDNetCrawler(GenericArticleCrawler):
    """ZDNet 新闻详情爬虫。"""

    base_url = "https://www.zdnet.com"
    content_xpath = '//div[contains(@class, "article-body")]'
