# -*- coding: utf-8 -*-
"""
新闻源注册表与文章链接自动发现 (自 NewsSpider/Minimal auto_crawler/service.py 抽取)。

由 Minimal 旧工程 - 调度层合并后的 service.py 中 "源发现" 部分独立而来:
- 平台 URL 检测 (PLATFORM_PATTERNS / detect_platform)
- 栏目页详情链接提取 (LINK_PATTERNS / _extract_column)
- RSS/Atom/RDF 源解析 (_extract_rss)
- 源注册表 (SOURCES / DOMESTIC_SOURCE_IDS)

数据来源 (用户拍板, Ver0.1.2 起):
- **源注册表真相 = DB sources 表**: 仅 enabled=True 的行参与构建;
  每次启动由 Services/App/sync.py 以 Config/Services.json 校验同步到 DB,
  本模块只从 DB 读, 不碰配置文件。
- platform_patterns / link_patterns 正则与 discovery HTTP 参数仍留
  Config/Services.json (平台识别基础设施, 非源业务数据)。

依赖:
- requests (_http_get_text 请求)
- Config.config (代理/超时/UA, 直连失败经 Core.json proxy 重试一次)
- Services.App.db (构建源注册表时按需连接)

用法:
    from Services.discovery import SOURCES  # 或
    from Services.discovery import discover_links
    links = discover_links("guardian")      # -> List[ArticleLink]
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional
from urllib.parse import urljoin
from xml.etree import ElementTree

import requests
from parsel import Selector

from Config.config import core_config, services_config

logger = logging.getLogger(__name__)

_CFG = services_config()["discovery"]
_DISC_HTTP = core_config()["discovery"]


# ================================================================
# 平台检测 (URL 正则 -> 平台 id)
# ================================================================
PLATFORM_PATTERNS = dict(_CFG["platform_patterns"])


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
    platform: re.compile(pattern)
    for platform, pattern in _CFG["link_patterns"].items()
}

DEFAULT_TIMEOUT = _DISC_HTTP["timeout"]
DEFAULT_HEADERS = {"User-Agent": _DISC_HTTP["user_agent"]}


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
    kind: str  # "rss" | "column" | "custom"
    discover: Callable[[], List[ArticleLink]]
    platform_ids: List[str] = field(default_factory=list)


def _http_get_text(url: str) -> str:
    """GET 请求: 直连失败 (超时/连接错误) 时自动改用代理重试一次。"""
    from Config.config import get_proxy_config
    from requests.exceptions import ConnectionError as RequestsConnectionError
    from requests.exceptions import Timeout as RequestsTimeout

    proxies = get_proxy_config()
    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.text
    except (RequestsConnectionError, RequestsTimeout) as exc:
        if not _DISC_HTTP["retry_via_proxy"] or proxies is None:
            raise
        time.sleep(_DISC_HTTP["retry_delay"])
        logger.info(
            "Direct connection failed (%s), retrying via proxy %s",
            exc, proxies["https"],
        )
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=DEFAULT_TIMEOUT,
                            proxies=proxies)
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
# 广告/推广 class token; 仅在单词/连字符边界匹配, 防止 ``advanced`` 等真实类名误伤。
_AD_HINT_RE = re.compile(
    r"(?<![a-z0-9])(?:banner|ad|ads|advert(?:isement|ising)?|adbox|promo|tui|gg)(?![a-z0-9])",
    re.IGNORECASE,
)


def _in_ad_container(a) -> bool:
    """链接自身或祖先元素带广告/推广 class token 则跳过。"""
    for node in a.xpath("ancestor-or-self::*[@class]"):
        cls = node.xpath("@class").get() or ""
        if _AD_HINT_RE.search(cls):
            return True
    return False


def _normalize_href(href: str, page_url: str, pattern: re.Pattern) -> Optional[str]:
    """补齐协议/相对路径 (// 前缀 -> https:; 无协议相对 -> urljoin), 返回匹配
    link_pattern 的绝对 URL (取正则匹配部分, 保留 ?/# 截断语义); 不匹配返回 None。"""
    if href.startswith("//"):
        href = "https:" + href
    elif not re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:", href):
        href = urljoin(page_url, href)
    match = pattern.match(href)
    return match.group(0) if match else None


def _extract_column(url: str, source_id: str, pattern: re.Pattern) -> List[ArticleLink]:
    """抓取栏目页 HTML, 提取匹配详情页形态的链接并保序去重。

    DOM 化 (parsel): 只取 <a href> 且跳过广告/推广容器 (banner/ad/gg 等类名),
    广告容器内出现的 URL 记入全局跳过集合 — 同一条横幅被页面多位置
    引用时任何位置都不再提取 (81.cn banner 轮播曾命中 link_pattern)。
    """
    try:
        html = _http_get_text(url)
    except requests.RequestException as exc:
        logging.warning("[%s] 栏目页获取失败, 跳过: %s", source_id, exc)
        return []
    candidates = []
    ad_urls = set()
    for a in Selector(text=html).xpath("//a[@href]"):
        href = (a.xpath("@href").get() or "").strip()
        if not href:
            continue
        href = _normalize_href(href, url, pattern)
        if href is None:
            continue
        if _in_ad_container(a):
            ad_urls.add(href)
        else:
            candidates.append(href)
    seen = set()
    links = []
    for href in candidates:
        if href in ad_urls or href in seen:
            continue
        seen.add(href)
        links.append(ArticleLink(url=href, title="", publish_time="", source=source_id))
    return links


# ================================================================
# 自定义发现逻辑 (无法纯数据化的特殊源)
# ================================================================
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


_CUSTOM_DISCOVERERS: Dict[str, Callable[[], List[ArticleLink]]] = {
    "cnn_home": _cnn_home_discover,
}


# ================================================================
# 源注册表 (真相源 = DB sources 表, 懒加载构建)
# ================================================================
def _row_to_spec(row) -> dict:
    """DB 源行 -> discovery 工厂所需 spec 字典 (config 列展开 + 元信息)。"""
    spec = dict(row.config or {})
    spec["id"] = row.id
    spec["name"] = row.name
    spec["kind"] = row.kind
    spec["platform_ids"] = list(row.platform_ids or [])
    return spec


def _make_rss_discover(spec: dict) -> Callable[[], List[ArticleLink]]:
    """RSS 类源 discover 工厂: 按配置的 feeds / url_replace / skip_substrings 构建。"""
    feeds = spec["feeds"]
    replace = spec.get("url_replace")
    skip = spec.get("skip_substrings") or []

    def discover() -> List[ArticleLink]:
        items: List[ArticleLink] = []
        for feed_url in feeds:
            items += _extract_rss(feed_url, spec["id"])
        filtered = [i for i in items if not any(s in i.url for s in skip)]
        if replace is not None and len(replace) == 2:
            for item in filtered:
                item.url = item.url.replace(replace[0], replace[1])
        return filtered

    return discover


def _make_column_discover(spec: dict) -> Callable[[], List[ArticleLink]]:
    """栏目页类源 discover 工厂。"""
    url = spec["column_url"]
    source_id = spec["id"]
    pattern = LINK_PATTERNS[spec["link_pattern"]]

    def discover() -> List[ArticleLink]:
        return _extract_column(url, source_id, pattern)

    return discover


def _build_sources_from_rows(rows) -> Dict[str, NewsSource]:
    """按 DB 源行构建注册表 (仅调用方传入的行参与, 通常为 enabled=True)。"""
    sources: Dict[str, NewsSource] = {}
    for row in rows:
        source_id = row.id
        custom = _CUSTOM_DISCOVERERS.get(source_id)
        spec = _row_to_spec(row)
        if custom is not None:
            discover = custom
        elif spec["kind"] == "rss":
            discover = _make_rss_discover(spec)
        elif spec["kind"] == "column":
            discover = _make_column_discover(spec)
        else:
            raise ValueError(
                f"未知源类型: {source_id} (kind={spec.get('kind')}), 需注册自定义 discover"
            )
        sources[source_id] = NewsSource(
            id=source_id,
            name=spec["name"],
            kind=spec["kind"],
            discover=discover,
            platform_ids=list(spec.get("platform_ids") or [source_id]),
        )
    return sources


def _load_sources_from_db() -> None:
    """首次调用时从 DB sources 表构建注册表 (仅启用源)。

    **原地更新** (clear + update) 而非重新绑定: 保持模块级 SOURCES /
    DOMESTIC_SOURCE_IDS 对象身份不变, 使 `from ... import SOURCES` 的既有
    引用方在懒加载完成后同样能看到 27 源 (修复 CLI 菜单空回归)。
    """
    from Services.App.db import SessionLocal
    from Services.App.models import Source
    from sqlalchemy import select

    with SessionLocal() as session:
        rows = list(session.scalars(select(Source).where(Source.enabled.is_(True))).all())
    SOURCES.clear()
    SOURCES.update(_build_sources_from_rows(rows))
    DOMESTIC_SOURCE_IDS.clear()
    DOMESTIC_SOURCE_IDS.update({row.id for row in rows if row.is_domestic})


SOURCES: Dict[str, NewsSource] = {}
DOMESTIC_SOURCE_IDS: set = set()
_sources_loaded = False
_load_lock = threading.Lock()


def ensure_sources_loaded() -> None:
    """懒加载入口: import 时不连库, 首次读源才构建 (线程安全)。

    调用方: 需要在模块级 SOURCES/DOMESTIC_SOURCE_IDS 构建完成后才能
    继续的业务 (如 CLI main.build_menu) 显式调用; get_source/is_domestic
    内部已自动触发。
    """
    global _sources_loaded
    if _sources_loaded:
        return
    with _load_lock:
        if not _sources_loaded:
            _load_sources_from_db()
            _sources_loaded = True

# 内部兼容别名 (旧代码引用)
_ensure_sources_loaded = ensure_sources_loaded


def is_domestic(source_id: str) -> bool:
    """是否为国内媒体源。"""
    _ensure_sources_loaded()
    return source_id in DOMESTIC_SOURCE_IDS


def get_source(source_id: str) -> NewsSource:
    """按 id 获取源, 未知 id 抛 ValueError。"""
    _ensure_sources_loaded()
    source = SOURCES.get(source_id)
    if source is None:
        raise ValueError(f"未知新闻源: {source_id}, 可选: {', '.join(SOURCES)}")
    return source


def discover_links(source_id: str) -> List[ArticleLink]:
    """发现指定源的文章链接, 自动过滤无法被现有提取器识别的平台。"""
    source = get_source(source_id)
    links = source.discover()
    return [link for link in links if detect_platform(link.url) is not None]