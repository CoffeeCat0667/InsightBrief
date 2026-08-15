# -*- coding: utf-8 -*-
"""
通用文章爬虫基类: 面向绝大多数新闻网站的通用提取逻辑。

提取策略 (按优先级):
1. JSON-LD (NewsArticle/Article/BlogPosting) -> headline / datePublished / author / articleBody
2. og: 系列 meta (og:title / og:description / article:published_time / article:author)
3. HTML 通用容器: 子类指定 content_xpath, 缺省自动探测 //article -> //main -> //div[@role=main]
4. 正文容器内按文档顺序提取 p/h2/h3/h4/li 为 TEXT, figure/img 为 IMAGE

新增平台只需写薄子类: 配置类属性 base_url / content_xpath (可选), 极少覆盖方法即可。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from parsel import Selector

from .base import BaseNewsCrawler
from Config.config import core_config
from .fetchers import CurlCffiFetcher, FetchRequest
from .models import ContentItem, ContentType, NewsItem, NewsMetaInfo

_SAVE_DIR = core_config()["paths"]["save_dir"]

_ARTICLE_TYPES = ("NewsArticle", "ReportageNewsArticle", "Article", "BlogPosting")
_TEXT_TAGS = ("p", "h2", "h3", "h4", "li", "blockquote", "pre")
_PUBLISH_TIME_HINTS = ("datePublished", "dateCreated", "uploadDate")
# <title> 兜底时剥离的站点名后缀, 如 "xxx - 新华网" / "xxx --观点--人民网 " / "xxx - 中国军网"
# 站点名前可带 0~1 个频道段 (人民网为 " --观点--人民网" 两段式)
_TITLE_SUFFIX = re.compile(
    r"\s*(?:--|-|—)\s*[^\-—]*?(?:\s*(?:--|-|—)\s*[^\-—]*)?"
    r"(?:人民网|新华网|中国军网|中国新闻网|央视网|新华社|光明网|经济日报|央广网|求是网)\s*$"
)


class GenericArticleCrawler(BaseNewsCrawler):
    """通用文章爬虫基类: 子类只需配置类属性, 极少覆盖方法。"""

    fetch_strategy = CurlCffiFetcher
    base_url: str = ""
    content_xpath: str = ""            # 正文容器 XPath, 空则自动探测 article/main
    block_xpath: str = ""              # 正文块 XPath (如 div.article-paragraph), 空则用默认标签集
    min_paragraph_chars: int = core_config()["generic"]["min_paragraph_chars"]
    min_content_chars: int = core_config()["generic"]["min_content_chars"]

    def __init__(self, new_url: str, save_path: str = _SAVE_DIR, headers=None, fetcher=None):
        super().__init__(new_url, save_path, headers=headers, fetcher=fetcher)

    # ---------------------------------------------------------------------- #
    # URL / id
    # ---------------------------------------------------------------------- #
    def get_article_id(self) -> str:
        """默认取 URL 最后一段作为 news_id (去除 .html/.htm 后缀); 子类可覆盖。"""
        tail = self.new_url.rstrip("/").split("/")[-1].split("?")[0]
        if not tail:
            # 某些站点 URL 以斜杠结尾、末段为空, 回退到上一段
            tail = self.new_url.rstrip("/").split("/")[-2].split("?")[0]
        if tail.lower().endswith((".html", ".htm")):
            tail = tail[: -5 if tail.lower().endswith(".html") else -4]
        if not tail:
            raise ValueError(f"无法从 URL 解析文章 ID: {self.new_url}")
        return tail

    def build_fetch_request(self) -> FetchRequest:
        request = super().build_fetch_request()
        request.impersonate = core_config()["fetch"]["generic_impersonate"]
        request.timeout = core_config()["fetch"]["generic_timeout"]
        return request

    # ---------------------------------------------------------------------- #
    # JSON-LD helpers
    # ---------------------------------------------------------------------- #
    def _jsonld_nodes(self, sel: Selector) -> List[Dict[str, Any]]:
        nodes: List[Dict[str, Any]] = []
        for script in sel.xpath('//script[@type="application/ld+json"]/text()').getall():
            try:
                data = json.loads(script)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(data, list):
                nodes.extend(item for item in data if isinstance(item, dict))
            elif isinstance(data, dict):
                graph = data.get("@graph")
                if isinstance(graph, list):
                    nodes.extend(item for item in graph if isinstance(item, dict))
                else:
                    nodes.append(data)
        return nodes

    def _pick_article_node(self, nodes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """优先挑选 NewsArticle 类型节点, 其次 Article/BlogPosting 等。"""
        candidates = []
        for node in nodes:
            types = node.get("@type", [])
            if isinstance(types, str):
                types = [types]
            if any(t in _ARTICLE_TYPES for t in types):
                candidates.append(node)
        for preferred in ("NewsArticle", "ReportageNewsArticle", "Article", "BlogPosting"):
            for node in candidates:
                types = node.get("@type", [])
                if isinstance(types, str):
                    types = [types]
                if preferred in types:
                    return node
        return None

    @staticmethod
    def _jsonld_author(node: Dict[str, Any]) -> tuple:
        """从 JSON-LD author 字段提取 (作者名, 作者主页)。"""
        author = node.get("author")
        if isinstance(author, list):
            author = author[0] if author else None
        if isinstance(author, dict):
            return str(author.get("name") or ""), str(author.get("url") or "")
        if isinstance(author, str):
            return author, ""
        return "", ""

    # ---------------------------------------------------------------------- #
    # Meta
    # ---------------------------------------------------------------------- #
    def parse_html_to_news_meta(self, html_content: str) -> NewsMetaInfo:
        self.logger.info("Start to parse html to news meta, news_url: %s", self.new_url)
        sel = Selector(text=html_content)
        node = self._pick_article_node(self._jsonld_nodes(sel))

        publish_time = ""
        if node:
            for hint in _PUBLISH_TIME_HINTS:
                if node.get(hint):
                    publish_time = str(node[hint])
                    break
        if not publish_time:
            publish_time = (
                sel.xpath('//meta[@property="article:published_time"]/@content').get("")
                or sel.xpath('//meta[@name="publishdate"]/@content').get("")
                or sel.xpath('//meta[@name="pubdate"]/@content').get("")
                or sel.xpath('//time/@datetime').get("")
                or sel.xpath('//time/text()').get("")
                or ""
            )

        author_name, author_url = "", ""
        if node:
            author_name, author_url = self._jsonld_author(node)
        if not author_name:
            author_name = (
                sel.xpath('//meta[@name="author"]/@content').get("")
                or sel.xpath('//meta[@property="article:author"]/@content').get("")
                or sel.xpath('//a[contains(@data-component, "byline")]//text()').get("")
                or ""
            ).strip()
            author_url = sel.xpath('//meta[@property="article:author"]/@content').get("") or author_url

        return NewsMetaInfo(
            publish_time=str(publish_time).strip(),
            author_name=str(author_name).strip(),
            author_url=str(author_url).strip(),
        )

    # ---------------------------------------------------------------------- #
    # Contents
    # ---------------------------------------------------------------------- #
    def _container(self, sel: Selector):
        if self.content_xpath:
            nodes = sel.xpath(self.content_xpath)
            if nodes:
                return nodes[0]
        for xp in ("//article", "//main", "//div[@role='main']", "//body"):
            nodes = sel.xpath(xp)
            if nodes:
                return nodes[0]
        return None

    def _normalize_url(self, url: str) -> str:
        url = url.strip()
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/") and self.base_url:
            return self.base_url.rstrip("/") + url
        return url

    def _extract_blocks(self, container) -> List[ContentItem]:
        """文档序提取正文: 文本块 + 图片, 去重/过滤噪声。"""
        if self.block_xpath:
            text_expr = self.block_xpath
        else:
            text_expr = " | ".join(f".//{tag}" for tag in _TEXT_TAGS)
        image_expr = ".//figure[.//img] | .//img[not(ancestor::figure)]"
        contents: List[ContentItem] = []
        seen_texts = set()
        # 内嵌 <script>/<style>/<template> 的文本是代码/配置噪声, 需排除
        text_nodes = ".//text()[not(ancestor::script)][not(ancestor::style)][not(ancestor::template)]"
        for element in container.xpath(f"{text_expr} | {image_expr}"):
            tag = element.root.tag
            if tag in _TEXT_TAGS or self.block_xpath:
                text = " ".join(element.xpath(text_nodes).getall())
                text = re.sub(r"\s+", " ", text).strip()
                if len(text) >= self.min_paragraph_chars and text not in seen_texts:
                    seen_texts.add(text)
                    contents.append(ContentItem(type=ContentType.TEXT, content=text, desc=text))
            elif tag == "figure":
                img = element.xpath(".//img/@src | .//img/@data-src").get()
                caption = " ".join(element.xpath(".//figcaption//text()").getall()).strip()
                if img:
                    contents.append(ContentItem(
                        type=ContentType.IMAGE, content=self._normalize_url(img), desc=caption
                    ))
            elif tag == "img":
                src = element.xpath("./@src").get() or element.xpath("./@data-src").get() or ""
                alt = element.xpath("./@alt").get("").strip()
                if src and not src.endswith((".svg", "placeholder", "blank")):
                    contents.append(ContentItem(
                        type=ContentType.IMAGE, content=self._normalize_url(src), desc=alt
                    ))
        return contents

    def _fallback_jsonld_body(self, html: str) -> List[ContentItem]:
        """部分站点 JSON-LD 带有完整 articleBody, 作为容器提取的兜底。

        段落通常以换行分隔; 少数站点 (如 Business Insider) 无换行, 按句子边界拆。
        """
        sel = Selector(text=html)
        node = self._pick_article_node(self._jsonld_nodes(sel))
        body = (node or {}).get("articleBody") if node else None
        if not body:
            return []
        body = str(body).strip()
        if len(body) < self.min_content_chars * 2:
            return []  # 只有摘要没有正文
        paragraphs = [p.strip() for p in re.split(r"\n+", body) if p.strip()]
        if len(paragraphs) < 2:
            paragraphs = [p.strip() for p in re.split(r"(?<=[.!?])\s+", body) if p.strip()]
        return [ContentItem(type=ContentType.TEXT, content=p, desc=p) for p in paragraphs]

    # ---------------------------------------------------------------------- #
    # Parse
    # ---------------------------------------------------------------------- #
    def parse_content(self, html: str) -> NewsItem:
        sel = Selector(text=html)
        node = self._pick_article_node(self._jsonld_nodes(sel))

        title = (node or {}).get("headline") if node else None
        if not title:
            title = sel.xpath('//meta[@property="og:title"]/@content').get("").strip()
        if not title:
            title = " ".join(sel.xpath("(//h1)[1]//text()").getall()).strip()
        if not title:
            # 部分官媒站点只有 <title> 标签 (如新华网/人民网/81.cn), 兜底并剥离站点后缀
            title = " ".join(sel.xpath('//title//text()').getall()).strip()
            if title:
                title = _TITLE_SUFFIX.sub("", title)
        title = " ".join(str(title).split()).strip()
        if not title:
            raise ValueError(f"Failed to get title: {self.new_url}")

        meta_info = self.parse_html_to_news_meta(html)
        contents: List[ContentItem] = []

        container = self._container(sel)
        if container is not None:
            contents = self._extract_blocks(container)
        text_len = sum(len(c.content) for c in contents if c.type == ContentType.TEXT)
        if text_len < self.min_content_chars:
            body_contents = self._fallback_jsonld_body(html)
            if len(body_contents) >= 2:
                contents = body_contents

        # 正文无图片时补 og:image 作为封面
        if not any(c.type == ContentType.IMAGE for c in contents):
            og_image = sel.xpath('//meta[@property="og:image"]/@content').get("")
            if og_image:
                contents.insert(0, ContentItem(
                    type=ContentType.IMAGE, content=self._normalize_url(og_image), desc=""
                ))

        return self.compose_news_item(
            title=title,
            meta_info=meta_info,
            contents=contents,
        )