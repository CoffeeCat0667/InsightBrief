# -*- coding: utf-8 -*-
"""新华网 (news.cn) 爬虫: 页面无 article/main 容器, 用 body 兜底 + title 标签。"""

from Core.generic import GenericArticleCrawler


class XinhuaNewsCrawler(GenericArticleCrawler):
    base_url = "https://www.news.cn"
    content_xpath = '//*[@id="detail"]'

    def get_article_id(self) -> str:
        tail = self.new_url.rstrip("/").split("/")[-1].split("?")[0]
        if tail == "c.html":
            tail = self.new_url.rstrip("/").split("/")[-2].split("?")[0]
        return tail