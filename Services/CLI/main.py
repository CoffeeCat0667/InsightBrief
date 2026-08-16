# -*- coding: utf-8 -*-
"""InsightBrief 主程序入口 (CLI)。

选择媒体 -> 自动发现最新一条新闻 -> 抓取解析:
  - 中文新闻直接显示
  - 其它语言自动翻译成中文显示
"""
from __future__ import annotations

import importlib
import inspect
import os
import sys
from collections import OrderedDict

# 项目根 = Services/CLI 的上两级; 先入 sys.path 保证 import 在任何调用方式下可解析
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Core.base import BaseNewsCrawler
from Services.discovery import SOURCES, discover_links, ensure_sources_loaded
from Services.translator import Translator, is_chinese

CATEGORY_LABELS = {
    "domesticGeneral": "国内综合",
    "domesticOfficialMedia": "国内官媒",
    "foreignGeneral": "外媒综合",
    "foreignFinance": "外媒财经",
    "foreignTechnology": "外媒科技",
}

MEDIA_CN_NAMES = {
    "xinhua": "新华网",
    "people": "人民网",
    "jfjb": "解放军报(中国军网)",
    "netease": "网易新闻",
    "sohu": "搜狐新闻",
    "bbc": "BBC News",
    "cnn": "CNN",
    "apnews": "AP News",
    "guardian": "卫报 Guardian",
    "nytimes": "纽约时报 New York Times",
    "aljazeera": "半岛电视台 Al Jazeera",
    "dw": "德国之声 DW",
    "npr": "NPR",
    "washingtonpost": "华盛顿邮报 Washington Post",
    "cnbc": "CNBC",
    "forbes": "福布斯 Forbes",
    "fortune": "财富 Fortune",
    "businessinsider": "Business Insider",
    "marketwatch": "MarketWatch",
    "techcrunch": "TechCrunch",
    "theverge": "The Verge",
    "wired": "Wired 连线",
    "arstechnica": "Ars Technica",
    "zdnet": "ZDNet",
    "engadget": "Engadget",
    "venturebeat": "VentureBeat",
}

# 项目根 = Services/CLI 的上两级 (兼容: python -m Services.CLI.main 或 python Services/CLI/main.py)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")


def build_menu() -> OrderedDict:
    """扫描 Clawer 分类目录, 构建 平台 -> (分类标签, 源 id, 媒体名) 菜单。"""
    ensure_sources_loaded()
    menu: OrderedDict = OrderedDict()
    clawer = os.path.join(PROJECT_ROOT, "Clawer")
    for cat in sorted(os.listdir(clawer)):
        cat_path = os.path.join(clawer, cat)
        if not os.path.isdir(cat_path):
            continue
        label = CATEGORY_LABELS.get(cat, cat)
        for entry in sorted(os.listdir(cat_path)):
            if entry == "__pycache__" or not os.path.isdir(
                os.path.join(cat_path, entry)
            ):
                continue
            platform = entry[:-5] if entry.endswith("_news") else entry
            source = next(
                (s for s in SOURCES.values() if platform in s.platform_ids),
                None,
            )
            if source is None:
                continue
            menu[platform] = (label, source.id, MEDIA_CN_NAMES.get(platform, platform))
        # 纯摘要源 (无任何爬虫目录): 附加到外媒综合分组
        if label == "外媒综合":
            for source in SOURCES.values():
                for platform in source.platform_ids:
                    if platform in menu:
                        continue
                    has_crawler = any(
                        os.path.isdir(os.path.join(clawer, c, f"{platform}_news"))
                        for c in os.listdir(clawer)
                    )
                    if not has_crawler:
                        menu[platform] = (
                            label, source.id, MEDIA_CN_NAMES.get(platform, source.name)
                        )
    return menu


def find_crawler_class(platform_id: str):
    """按平台 id 定位 Clawer/<cat>/<platform>_news 中的爬虫类。"""
    clawer = os.path.join(PROJECT_ROOT, "Clawer")
    for cat in os.listdir(clawer):
        modname = f"{platform_id}_news"
        if not os.path.isdir(os.path.join(clawer, cat, modname)):
            continue
        mod = importlib.import_module(f"Clawer.{cat}.{modname}.{modname}")
        for _, cls in inspect.getmembers(mod, inspect.isclass):
            if (
                issubclass(cls, BaseNewsCrawler)
                and cls.__module__ == mod.__name__
                and cls is not BaseNewsCrawler
            ):
                return cls
    return None


def print_menu(menu: OrderedDict) -> None:
    """按分类打印媒体菜单。"""
    print("\n" + "=" * 60)
    print("  InsightBrief · 新闻阅读器")
    print("=" * 60)
    last_label = None
    index = 1
    for platform, (label, _, name) in menu.items():
        if label != last_label:
            print(f"\n  [ {label} ]")
            last_label = label
        print(f"    {index:>2}. {name}")
        index += 1
    print("\n" + "=" * 60)


def display(text: str) -> str:
    """中文直显, 其它语言翻译为中文。"""
    if is_chinese(text):
        return text
    return translator.translate(text)


def show_news_summary(name: str, link) -> None:
    """摘要型源: 无文章页可抓, 直接展示 RSS 自带的标题/时间/摘要。"""
    print("[2/3] 该源为外部 RSS 摘要模式 (站点正文不可抓取)...")
    print("[3/3] 翻译/排版中...\n")
    print("─" * 60)
    print(f"  {display(link.title)}")
    print("─" * 60)
    print(f"  媒体  : {name}")
    print(f"  时间  : {link.publish_time or '-'}")
    print(f"  链接  : {link.url}")
    print("=" * 60 + "\n")
    brief = (link.content or "").strip()
    if not brief:
        print("  (该条目无摘要)\n")
        return
    print(display(brief))
    print("\n" + "=" * 60)


def show_news(menu: OrderedDict, choice: int) -> None:
    """抓取选定媒体最新一条新闻并显示。"""
    platform = list(menu.keys())[choice - 1]
    _, source_id, name = menu[platform]

    print(f"\n[1/3] 正在发现 {name} 的最新新闻链接...")
    links = discover_links(source_id)
    if not links:
        print("  未发现可抓取的文章链接, 请更换媒体或稍后重试。")
        return
    latest = links[0]

    print("[2/3] 正在抓取文章正文...")
    crawler_cls = find_crawler_class(platform)
    if crawler_cls is None:
        show_news_summary(name, latest)
        return
    item = crawler_cls(latest.url).run(persist=False)

    print("[3/3] 翻译/排版中...\n")
    print("─" * 60)
    print(f"  {display(item.title)}")
    print("─" * 60)
    print(f"  媒体  : {name}")
    print(f"  作者  : {item.meta_info.author_name or '-'}")
    print(f"  时间  : {item.meta_info.publish_time or '-'}")
    print(f"  链接  : {latest.url}")
    print("=" * 60 + "\n")

    body = "\n".join(item.texts).strip()
    if not body:
        print("  (此页未提取到正文)\n")
        return
    print(display(body))
    print("\n" + "=" * 60)


def main() -> None:
    menu = build_menu()
    if not menu:
        print("未发现任何媒体, 请确认 Clawer/ 目录结构完整。")
        sys.exit(1)

    print_menu(menu)
    while True:
        raw = input("\n请输入媒体编号抓取最新新闻 (q 退出): ").strip()
        if raw.lower() in ("q", "quit", "exit"):
            print("再见。")
            return
        if not raw.isdigit():
            print("请输入有效编号。")
            continue
        choice = int(raw)
        if not 1 <= choice <= len(menu):
            print(f"编号超出范围 (1-{len(menu)})。")
            continue
        try:
            show_news(menu, choice)
        except Exception as exc:
            print(f"\n抓取失败: {type(exc).__name__}: {exc}")

        if input("\n继续浏览? (回车继续 / q 退出): ").strip().lower() in ("q", "quit", "exit"):
            print("再见。")
            return


translator = Translator()

if __name__ == "__main__":
    main()