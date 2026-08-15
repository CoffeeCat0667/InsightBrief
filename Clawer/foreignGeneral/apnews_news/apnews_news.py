# -*- coding: utf-8 -*-
# description: 采集 AP News 新闻详情 (通用解析基类薄子类)
from Config.config import platform_config
from Core.generic import GenericArticleCrawler


_CFG = platform_config("apnews")


class APNewsCrawler(GenericArticleCrawler):
    """AP News 新闻详情爬虫。"""

    base_url = _CFG["base_url"]
    content_xpath = _CFG.get("content_xpath", "")
