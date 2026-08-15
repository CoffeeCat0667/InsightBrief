# -*- coding: utf-8 -*-
"""人民网 (people.com.cn) 爬虫: 正文容器 id=rm_txt_zw, 时间在 id=newstime 文本。"""

from parsel import Selector

from Config.config import platform_config
from Core.generic import GenericArticleCrawler


_CFG = platform_config("people")


class PeopleNewsCrawler(GenericArticleCrawler):
    base_url = _CFG["base_url"]
    content_xpath = _CFG.get("content_xpath", "")

    def parse_html_to_news_meta(self, html_content: str):
        meta = super().parse_html_to_news_meta(html_content)
        if not meta.publish_time:
            sel = Selector(text=html_content)
            time_text = " ".join(sel.xpath('//*[@id="newstime"]//text()').getall()).strip()
            meta.publish_time = time_text
        return meta