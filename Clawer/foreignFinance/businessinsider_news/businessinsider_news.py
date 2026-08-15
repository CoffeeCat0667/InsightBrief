# -*- coding: utf-8 -*-
# description: 采集 Business Insider 新闻详情 (通用解析基类薄子类)
from Core.generic import GenericArticleCrawler


class BusinessInsiderCrawler(GenericArticleCrawler):
    """Business Insider 新闻详情爬虫。

    正文容器类名不稳定, 依赖 JSON-LD articleBody 兜底 (内容完整)。
    """

    base_url = "https://www.businessinsider.com"
    content_xpath = ""
    min_content_chars = 200
