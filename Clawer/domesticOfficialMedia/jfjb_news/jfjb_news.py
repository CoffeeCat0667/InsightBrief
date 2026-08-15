# -*- coding: utf-8 -*-
"""解放军报 (中国军网 81.cn) 爬虫: 正文容器 id=article-content。"""

from Core.generic import GenericArticleCrawler


class JfjbNewsCrawler(GenericArticleCrawler):
    base_url = "http://www.81.cn"
    content_xpath = '//*[@id="article-content"]'