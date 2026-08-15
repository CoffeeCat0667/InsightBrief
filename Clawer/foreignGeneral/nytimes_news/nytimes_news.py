# -*- coding: utf-8 -*-
# description: 采集 The New York Times 中文版新闻详情 (正文为 div.article-paragraph 块)
from Core.generic import GenericArticleCrawler


class NYTimesCrawler(GenericArticleCrawler):
    """The New York Times 中文版 (cn.nytimes.com) 新闻详情爬虫。"""

    base_url = "https://cn.nytimes.com"
    content_xpath = '//section[contains(@class, "article-body")]'
    block_xpath = ".//div[contains(@class, 'article-paragraph')]"