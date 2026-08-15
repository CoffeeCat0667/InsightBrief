# -*- coding: utf-8 -*-
# description: 采集 Engadget 新闻详情 (通用解析基类薄子类)
from Config.config import platform_config
from Core.generic import GenericArticleCrawler


_CFG = platform_config("engadget")


class EngadgetCrawler(GenericArticleCrawler):
    """Engadget 新闻详情爬虫。"""

    base_url = _CFG["base_url"]
    content_xpath = _CFG.get("content_xpath", "")
