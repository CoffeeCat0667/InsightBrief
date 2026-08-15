# -*- coding: utf-8 -*-
# description: 采集 CNBC 新闻详情 (通用解析基类薄子类)
from Core.generic import GenericArticleCrawler


class CNBCNewsCrawler(GenericArticleCrawler):
    """CNBC 新闻详情爬虫。"""

    base_url = "https://www.cnbc.com"
    content_xpath = '//div[contains(@class, "ArticleBody")]'
