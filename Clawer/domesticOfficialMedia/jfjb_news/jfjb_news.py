# -*- coding: utf-8 -*-
"""解放军报 (中国军网 81.cn) 爬虫: 正文容器 id=article-content。"""

from Config.config import platform_config
from Core.generic import GenericArticleCrawler


_CFG = platform_config("jfjb")


class JfjbNewsCrawler(GenericArticleCrawler):
    base_url = _CFG["base_url"]
    content_xpath = _CFG.get("content_xpath", "")