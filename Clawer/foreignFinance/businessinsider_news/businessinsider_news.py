# -*- coding: utf-8 -*-
# description: 采集 Business Insider 新闻详情 (通用解析基类薄子类)
from Config.config import platform_config
from Core.generic import GenericArticleCrawler


_CFG = platform_config("businessinsider")


class BusinessInsiderCrawler(GenericArticleCrawler):
    """Business Insider 新闻详情爬虫。

    正文容器类名不稳定, 依赖 JSON-LD articleBody 兜底 (内容完整)。
    """

    base_url = _CFG["base_url"]
    content_xpath = _CFG.get("content_xpath", "")
    min_content_chars = _CFG.get("min_content_chars", GenericArticleCrawler.min_content_chars)
