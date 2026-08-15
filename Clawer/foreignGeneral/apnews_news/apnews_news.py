# -*- coding: utf-8 -*-
# description: 采集 AP News 新闻详情 (通用解析基类薄子类)
from Core.generic import GenericArticleCrawler


class APNewsCrawler(GenericArticleCrawler):
    """AP News 新闻详情爬虫。"""

    base_url = "https://apnews.com"
    content_xpath = '//div[contains(@class, "RichTextStoryBody")]'
