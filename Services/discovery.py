# -*- coding: utf-8 -*-
"""
新闻源注册表与文章链接自动发现 (自 NewsSpider/Minimal auto_crawler/service.py 抽取)。

由 Minimal 旧工程 - 调度层合并后的 service.py 中 "源发现" 部分独立而来:
- 平台 URL 检测 (PLATFORM_PATTERNS / detect_platform)
- 栏目页详情链接提取 (LINK_PATTERNS / _extract_column)
- RSS/Atom/RDF 源解析 (_extract_rss)
- 源注册表 (MEDIA_SOURCES / SOURCES / DOMESTIC_SOURCE_IDS)
- 统一入口 discover_links(source_id)

依赖:
- requests (_http_get_text 请求)
- Core.fetchers.get_proxy_config (直连失败经 CRAWL_PROXY 代理重试一次)

用法:
    from Services.discovery import SOURCES  # 或
    from Services.discovery import discover_links
    links = discover_links("guardian")      # -> List[ArticleLink]
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional
from xml.etree import ElementTree

import requests

logger = logging.getLogger(__name__)


# ================================================================
# 平台检测 (URL 正则 -> 平台 id)
# ================================================================
PLATFORM_PATTERNS = {
    "netease": r"https?://www\.163\.com/(news|dy)/article/",
    "sohu": r"https?://www\.sohu\.com/a/",
    "bbc": r"https?://www\.bbc\.com/news/articles/",
    "cnn": r"https?://(edition\.|www\.)?cnn\.com/\d{4}/\d{2}/\d{2}/",
    # ---- 外媒综合 ----
    "apnews": r"https?://apnews\.com/",
    "guardian": r"https?://(?:www\.)?theguardian\.com/",
    "nytimes": r"https?://(?:www\.|cn\.)?nytimes\.com/(?:[a-z-]+/)?\d{4,8}/",
    "aljazeera": r"https?://(?:www\.)?aljazeera\.com/",
    "dw": r"https?://(?:www\.)?dw\.com/",
    "npr": r"https?://(?:www\.)?npr\.org/\d{4}/",
    # ---- 外媒综合 (摘要型) ----
    "washingtonpost": r"https?://(?:www\.)?washingtonpost\.com/",
    # ---- 外媒财经 ----
    "cnbc": r"https?://(?:www\.)?cnbc\.com/\d{4}/",
    "forbes": r"https?://(?:www\.)?forbes\.com/",
    "fortune": r"https?://fortune\.com/",
    "businessinsider": r"https?://(?:www\.)?businessinsider\.com/",
    "marketwatch": r"https?://(?:www\.)?marketwatch\.com/story/",
    # ---- 外媒科技 ----
    "techcrunch": r"https?://techcrunch\.com/\d{4}/",
    "theverge": r"https?://(?:www\.)?theverge\.com/(?:[a-z0-9-]+/)?\d{4,}/",
    "wired": r"https?://(?:www\.)?wired\.com/story/",
    "arstechnica": r"https?://arstechnica\.com/",
    "zdnet": r"https?://(?:www\.)?zdnet\.com/article/",
    "engadget": r"https?://(?:www\.)?engadget\.com/\d+/",
    "venturebeat": r"https?://venturebeat\.com/",
    # ---- 国内官媒 ----
    "xinhua": r"https?://www\.news\.cn/[a-z]+/2\d{7}/",
    "people": r"https?://[a-z]+\.people\.com\.cn/n\d/\d{4}/\d{4}/",
    "jfjb": r"https?://www\.81\.cn/[a-z0-9_]+/\d+\.html",
}


def detect_platform(url: str) -> Optional[str]:
    """按 URL 正则检测平台 id; 无法识别返回 None。"""
    for platform, pattern in PLATFORM_PATTERNS.items():
        if re.match(pattern, url):
            return platform
    return None


# ================================================================
# 栏目页详情链接形态 (首页 HTML 内匹配详情 URL 的正则)
# ================================================================
LINK_PATTERNS = {
    "netease": re.compile(r"https?://www\.163\.com/(?:news|dy)/article/[^\"'<>\s?#]+"),
    "sohu": re.compile(r"(?:https?:)?//(?:www\.)?sohu\.com/a/\d+[^\"'<>\s?#]*"),
    "bbc": re.compile(r"https?://www\.bbc\.com/news/articles/[^\"'<>\s?#]+"),
    "cnn": re.compile(r"(?:https?:)?//(?:www\.|edition\.)?cnn\.com/\d{4}/\d{2}/\d{2}/[^\"'<>\s?#]+\.html"),
    "apnews": re.compile(r"https?://apnews\.com/article/[^\"'<>\s?#]+"),
    "xinhua": re.compile(r"https?://www\.news\.cn/[a-z]+/2\d{7}/[A-Za-z0-9_\-\.]+/c\.html"),
    "people": re.compile(r"https?://[a-z]+\.people\.com\.cn/n\d/\d{4}/\d{4}/c\d+-\d+\.html"),
    "jfjb": re.compile(r"https?://www\.81\.cn/[a-z0-9_]+/\d+\.html"),
}

DEFAULT_TIMEOUT = 15.0
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
}


@dataclass
class ArticleLink:
    """一条待提取的文章链接。"""

    url: str
    title: str = ""
    publish_time: str = ""
    source: str = ""
    content: str = ""  # 全文型 RSS 的正文, 空表示需抓详情页


@dataclass
class NewsSource:
    """一个新闻源的描述与发现函数。"""

    id: str
    name: str
    kind: str  # "rss" | "column"
    discover: Callable[[], List[ArticleLink]]
    platform_ids: List[str] = field(default_factory=list)


def _http_get_text(url: str) -> str:
    """GET 请求: 直连失败 (超时/连接错误) 时自动改用代理重试一次。"""
    from Core.fetchers import get_proxy_config
    from requests.exceptions import ConnectionError as RequestsConnectionError
    from requests.exceptions import Timeout as RequestsTimeout

    proxies = get_proxy_config()
    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.text
    except (RequestsConnectionError, RequestsTimeout) as exc:
        time.sleep(1.0)
        kwargs = {"proxies": proxies} if proxies is not None else {}
        logger.info(
            "Direct connection failed (%s), retrying via proxy %s",
            exc, proxies["https"] if proxies else None,
        )
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=DEFAULT_TIMEOUT, **kwargs)
        resp.raise_for_status()
        return resp.text


# ================================================================
# RSS / Atom / RDF 源解析
# ================================================================
def _extract_rss(url: str, source_id: str) -> List[ArticleLink]:
    """解析 RSS 2.0 / Atom / RDF 源, 返回文章链接列表。单个源失败时告警并返回空列表。"""
    try:
        text = _http_get_text(url)
    except requests.RequestException as exc:
        logging.warning("[%s] RSS 获取失败, 跳过: %s", source_id, exc)
        return []
    try:
        root = ElementTree.fromstring(text.encode("utf-8", errors="replace"))
    except ElementTree.ParseError as exc:
        logging.warning("[%s] RSS 解析失败, 跳过: %s", source_id, exc)
        return []

    items = []
    for node in root.iter():
        if _local_tag(node.tag) in ("item", "entry"):
            title = (_child_text(node, "title") or "").strip()
            link = _find_link(node)
            pub_date = _find_pub_date(node)
            content = _find_content(node)
            if link:
                items.append(ArticleLink(
                    url=link, title=title, publish_time=pub_date,
                    source=source_id, content=content,
                ))
    return items


def _local_tag(tag: str) -> str:
    """剥离 XML 命名空间, 返回本地标签名。"""
    return tag.rsplit("}", 1)[-1]


def _child_text(node: ElementTree.Element, local_name: str) -> Optional[str]:
    for child in node:
        if _local_tag(child.tag) == local_name:
            return child.text
    return None


def _find_link(node: ElementTree.Element) -> Optional[str]:
    """RSS <link>text</link> 或 Atom <link href=.../> 均可解析。"""
    for child in node:
        if _local_tag(child.tag) == "link":
            return (child.text or child.get("href") or "").strip() or None
    return None


def _find_pub_date(node: ElementTree.Element) -> str:
    for tag in ("pubDate", "published", "updated"):
        text = _child_text(node, tag)
        if text:
            return text.strip()
    return ""


def _find_content(node: ElementTree.Element) -> str:
    """取 RSS 正文, 全文优先: content:encoded / Atom <content> > <description>。"""
    for tag in ("encoded", "content", "description"):
        for child in node:
            if _local_tag(child.tag) == tag and child.text:
                return child.text.strip()
    return ""


# ================================================================
# 栏目页发现 (首页 HTML + 详情链接形态正则)
# ================================================================
def _extract_column(url: str, source_id: str, pattern: re.Pattern) -> List[ArticleLink]:
    """抓取栏目页 HTML, 提取匹配详情页形态的链接并保序去重。"""
    try:
        html = _http_get_text(url)
    except requests.RequestException as exc:
        logging.warning("[%s] 栏目页获取失败, 跳过: %s", source_id, exc)
        return []
    seen = set()
    links = []
    for match in pattern.finditer(html):
        link = match.group(0)
        if link.startswith("//"):
            link = "https:" + link
        if link not in seen:
            seen.add(link)
            links.append(ArticleLink(url=link, title="", publish_time="", source=source_id))
    return links


# ================================================================
# 各源发现函数
# ================================================================
def _bbc_rss_discover() -> List[ArticleLink]:
    """BBC World + Tech 两个官方 RSS。"""
    items = _extract_rss("https://feeds.bbci.co.uk/news/world/rss.xml", "bbc_rss")
    items += _extract_rss("https://feeds.bbci.co.uk/news/technology/rss.xml", "bbc_rss")
    for item in items:
        item.url = item.url.replace("www.bbc.co.uk", "www.bbc.com")
    return items


def _bbc_china_discover() -> List[ArticleLink]:
    """BBC China 专题官方 RSS (过滤 /videos/ 链接)。"""
    items = _extract_rss("https://feeds.bbci.co.uk/news/world/asia/china/rss.xml", "bbc_china")
    filtered = [item for item in items if "/videos/" not in item.url]
    for item in filtered:
        item.url = item.url.replace("www.bbc.co.uk", "www.bbc.com")
    return filtered


def _netease_domestic_discover() -> List[ArticleLink]:
    return _extract_column("https://news.163.com/domestic/", "netease_domestic", LINK_PATTERNS["netease"])


def _sohu_news_discover() -> List[ArticleLink]:
    return _extract_column("https://news.sohu.com/", "sohu_news", LINK_PATTERNS["sohu"])


def _cnn_home_discover() -> List[ArticleLink]:
    """CNN 首页 (rss.cnn.com 在某些网络被屏蔽, 从首页内嵌 JSON 提取文章路径)。

    过滤 video/live-news/gallery 等非文章页: 这些页面无正文结构, 提取器拿不到内容。
    """
    html = _http_get_text("https://www.cnn.com/")
    seen = set()
    links = []
    for match in re.finditer(r'"/(\d{4}/\d{2}/\d{2}/[^"]+)"', html):
        path = match.group(1)
        if any(skip in path for skip in ("/video/", "/live-news/", "/gallery/")):
            continue
        if path not in seen:
            seen.add(path)
            links.append(ArticleLink(url="https://www.cnn.com/" + path, source="cnn_home"))
    return links


def _apnews_home_discover() -> List[ArticleLink]:
    return _extract_column("https://apnews.com/", "apnews", LINK_PATTERNS["apnews"])


def _xinhua_home_discover() -> List[ArticleLink]:
    return _extract_column("https://www.news.cn/", "xinhua", LINK_PATTERNS["xinhua"])


def _people_home_discover() -> List[ArticleLink]:
    return _extract_column("http://www.people.com.cn/", "people", LINK_PATTERNS["people"])


def _jfjb_home_discover() -> List[ArticleLink]:
    return _extract_column("http://www.81.cn/", "jfjb", LINK_PATTERNS["jfjb"])


def _make_rss_discover(feed_urls: List[str], source_id: str) -> Callable[[], List[ArticleLink]]:
    """单个/多个 RSS feed 的 discover 工厂。"""

    def discover() -> List[ArticleLink]:
        items: List[ArticleLink] = []
        for feed_url in feed_urls:
            items += _extract_rss(feed_url, source_id)
        return items

    return discover


# ================================================================
# 源注册表
# ================================================================
# 外媒主流媒体源注册表
MEDIA_SOURCES_DEF = [
    # ---- 综合 ----
    ("apnews", "AP News", "column", _apnews_home_discover),
    ("guardian", "The Guardian", "rss", _make_rss_discover(["https://www.theguardian.com/world/rss"], "guardian")),
    ("nytimes", "The New York Times", "rss", _make_rss_discover(["https://quanwenrss.com/nytime"], "nytimes")),
    ("aljazeera", "Al Jazeera", "rss", _make_rss_discover(["https://www.aljazeera.com/xml/rss/all.xml"], "aljazeera")),
    ("dw", "Deutsche Welle", "rss", _make_rss_discover(["https://rss.dw.com/rdf/rss-en-all"], "dw")),
    ("npr", "NPR", "rss", _make_rss_discover(["https://feeds.npr.org/1001/rss.xml"], "npr")),
    ("washingtonpost", "The Washington Post", "rss",
     _make_rss_discover(["https://feeds.washingtonpost.com/rss/world"], "washingtonpost")),
    # ---- 财经 ----
    ("cnbc", "CNBC", "rss", _make_rss_discover(["https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"], "cnbc")),
    ("forbes", "Forbes", "rss", _make_rss_discover(["https://www.forbes.com/innovation/feed/", "https://www.forbes.com/business/feed/"], "forbes")),
    ("fortune", "Fortune", "rss", _make_rss_discover(["https://fortune.com/feed/"], "fortune")),
    ("businessinsider", "Business Insider", "rss", _make_rss_discover(["https://www.businessinsider.com/rss"], "businessinsider")),
    ("marketwatch", "MarketWatch", "rss", _make_rss_discover(["https://feeds.content.dowjones.io/public/rss/mw_topstories"], "marketwatch")),
    # ---- 科技 ----
    ("techcrunch", "TechCrunch", "rss", _make_rss_discover(["https://techcrunch.com/feed/"], "techcrunch")),
    ("theverge", "The Verge", "rss", _make_rss_discover(["https://www.theverge.com/rss/index.xml"], "theverge")),
    ("wired", "WIRED", "rss", _make_rss_discover(["https://www.wired.com/feed/rss"], "wired")),
    ("arstechnica", "Ars Technica", "rss", _make_rss_discover(["https://feeds.arstechnica.com/arstechnica/index"], "arstechnica")),
    ("zdnet", "ZDNet", "rss", _make_rss_discover(["https://www.zdnet.com/news/rss.xml"], "zdnet")),
    ("engadget", "Engadget", "rss", _make_rss_discover(["https://www.engadget.com/rss.xml"], "engadget")),
    ("venturebeat", "VentureBeat", "rss", _make_rss_discover(["https://venturebeat.com/feed/"], "venturebeat")),
]

MEDIA_SOURCES = {
    source_id: NewsSource(id=source_id, name=name, kind=kind, discover=discover, platform_ids=[source_id])
    for source_id, name, kind, discover in MEDIA_SOURCES_DEF
}

# 国内媒体源 id 集合 (pipeline 用来做国内占比权重分配)
DOMESTIC_SOURCE_IDS = {"netease_domestic", "sohu_news", "xinhua", "people", "jfjb"}


def is_domestic(source_id: str) -> bool:
    """是否为国内媒体源。"""
    return source_id in DOMESTIC_SOURCE_IDS


# 内置源注册表
SOURCES = {
    "bbc_rss": NewsSource(id="bbc_rss", name="BBC News (RSS)", kind="rss",
                          discover=_bbc_rss_discover, platform_ids=["bbc"]),
    "bbc_china": NewsSource(id="bbc_china", name="BBC News · 中国专题", kind="rss",
                            discover=_bbc_china_discover, platform_ids=["bbc"]),
    "netease_domestic": NewsSource(id="netease_domestic", name="网易新闻·国内", kind="column",
                                   discover=_netease_domestic_discover, platform_ids=["netease"]),
    "sohu_news": NewsSource(id="sohu_news", name="搜狐新闻", kind="column",
                            discover=_sohu_news_discover, platform_ids=["sohu"]),
    "cnn_home": NewsSource(id="cnn_home", name="CNN News (首页)", kind="column",
                           discover=_cnn_home_discover, platform_ids=["cnn"]),
    "xinhua": NewsSource(id="xinhua", name="新华网", kind="column",
                         discover=_xinhua_home_discover, platform_ids=["xinhua"]),
    "people": NewsSource(id="people", name="人民网(人民日报)", kind="column",
                         discover=_people_home_discover, platform_ids=["people"]),
    "jfjb": NewsSource(id="jfjb", name="解放军报(中国军网)", kind="column",
                       discover=_jfjb_home_discover, platform_ids=["jfjb"]),
}

SOURCES.update(MEDIA_SOURCES)


def get_source(source_id: str) -> NewsSource:
    """按 id 获取源, 未知 id 抛 ValueError。"""
    source = SOURCES.get(source_id)
    if source is None:
        raise ValueError(f"未知新闻源: {source_id}, 可选: {', '.join(SOURCES)}")
    return source


def discover_links(source_id: str) -> List[ArticleLink]:
    """发现指定源的文章链接, 自动过滤无法被现有提取器识别的平台。"""
    source = get_source(source_id)
    links = source.discover()
    return [link for link in links if detect_platform(link.url) is not None]