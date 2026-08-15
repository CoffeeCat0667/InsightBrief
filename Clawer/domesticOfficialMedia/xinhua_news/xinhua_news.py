# -*- coding: utf-8 -*-
"""新华网 (news.cn) 爬虫: 页面无 article/main 容器, 用 body 兜底 + title 标签。"""

from Config.config import platform_config
from Core.generic import GenericArticleCrawler


_CFG = platform_config("xinhua")


class XinhuaNewsCrawler(GenericArticleCrawler):
    base_url = _CFG["base_url"]
    content_xpath = _CFG.get("content_xpath", "")

    def get_article_id(self) -> str:
        tail = self.new_url.rstrip("/").split("/")[-1].split("?")[0]
        if tail == "c.html":
            tail = self.new_url.rstrip("/").split("/")[-2].split("?")[0]
        return tail