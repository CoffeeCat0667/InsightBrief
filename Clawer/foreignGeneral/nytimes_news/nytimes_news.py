# -*- coding: utf-8 -*-
# description: 采集 The New York Times 中文版新闻详情 (正文为 div.article-paragraph 块)
from Config.config import platform_config
from Core.generic import GenericArticleCrawler


_CFG = platform_config("nytimes")


class NYTimesCrawler(GenericArticleCrawler):
    """The New York Times 中文版 (cn.nytimes.com) 新闻详情爬虫。"""

    base_url = _CFG["base_url"]
    content_xpath = _CFG.get("content_xpath", "")
    block_xpath = _CFG.get("block_xpath", "")