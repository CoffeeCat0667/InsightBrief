#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""自动测速工具: 实测各平台真实抓取耗时, 计算建议 fetch_timeout 并写回 Clawer.json。

超时唯一来源 = 各平台条目 fetch_timeout (平台级, 无全局 timeout 配置)。
本脚本在部署环境 (如新服务器/新网络) 上跑一遍, 即可按实测重新调优:

    python Tools/measure_fetch_timeout.py            # 全量实测并写回
    python Tools/measure_fetch_timeout.py --dry-run  # 只打印, 不写文件
    python Tools/measure_fetch_timeout.py --platform zdnet   # 只测单个平台

建议值规则: 实测耗时 t 秒 -> max(20, 向上取整到 5 的 t*1.5) —
留 50% 余量且不低于 20s (快站点也不宜过小, 防抖动误杀)。
取值为 5 的倍数, 保持配置整洁。
"""
from __future__ import annotations

import argparse
import importlib
import inspect
import json
import logging
import math
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from Core.base import BaseNewsCrawler  # noqa: E402
from Config.config import get_proxy_config, platform_config  # noqa: E402

FLAWER_JSON = PROJECT_ROOT / "Config" / "Clawer.json"
MIN_TIMEOUT = 20.0
DEFAULT_TIMEOUT = 30.0


def find_crawler_class(platform_id: str) -> Optional[type]:
    """按平台 id 定位 Clawer/<cat>/<platform>_news 中的爬虫类。"""
    clawer = PROJECT_ROOT / "Clawer"
    if not clawer.is_dir():
        return None
    for cat in clawer.iterdir():
        modname = f"{platform_id}_news"
        if not (cat / modname).is_dir():
            continue
        try:
            mod = importlib.import_module(f"Clawer.{cat.name}.{modname}.{modname}")
        except ImportError:
            continue
        for _, cls in inspect.getmembers(mod, inspect.isclass):
            if (
                issubclass(cls, BaseNewsCrawler)
                and cls.__module__ == mod.__name__
                and cls is not BaseNewsCrawler
            ):
                return cls
    return None


def measure_once(platform_id: str, crawler_cls: type, url: str) -> float:
    """单次真实抓取计时 (无重试, 直连失败自动走代理回退, 与生产链路一致)。

    crawler 的 INFO 日志临时静音, 保证进度条界面干净。
    """
    crawler = crawler_cls(url, platform_id=platform_id)
    level = crawler.logger.level
    crawler.logger.setLevel(logging.WARNING)
    try:
        request = crawler.build_fetch_request()
        if request.proxies is None:
            request.proxies = get_proxy_config()
        start = time.monotonic()
        crawler.fetcher.fetch(request)
        return time.monotonic() - start
    finally:
        crawler.logger.setLevel(level)


def suggest_timeout(seconds: Optional[float]) -> float:
    """实测耗时 -> 建议超时: max(20, 5 的倍数向上取整 t*1.5)。"""
    if seconds is None or seconds <= 0:
        return DEFAULT_TIMEOUT
    return max(MIN_TIMEOUT, math.ceil(seconds * 1.5 / 5.0) * 5.0)


def _start_progress(pid: str, idx: int, total: int) -> Optional[threading.Event]:
    """终端进度行: 抓取中动画 (每 0.2s 重绘已用时), 返回停止信号。

    非 TTY (输出重定向/管道) 时返回 None, 不输出动画行。
    """
    if not sys.stderr.isatty():
        return None
    stop = threading.Event()
    start = time.monotonic()

    def _draw():
        while not stop.is_set():
            sys.stderr.write(
                f"\r[{idx:>2}/{total}] {pid:<14s} 抓取中 {time.monotonic() - start:6.1f}s"
            )
            sys.stderr.flush()
            stop.wait(0.2)

    threading.Thread(target=_draw, daemon=True).start()
    return stop


def _clear_progress() -> None:
    sys.stderr.write("\r" + " " * 72 + "\r")
    sys.stderr.flush()


def load_platforms(raw_path: Path) -> Dict[str, dict]:
    d = json.loads(raw_path.read_text(encoding="utf-8"))
    return d["platforms"]


def main() -> int:
    ap = argparse.ArgumentParser(description="实测平台抓取耗时并写回 Clawer.json fetch_timeout")
    ap.add_argument("--dry-run", action="store_true", help="只打印结果, 不写文件")
    ap.add_argument("--platform", action="append", help="只测指定平台 id (可多次指定)");
    args = ap.parse_args()

    platforms = load_platforms(FLAWER_JSON)
    ids = args.platform if args.platform else list(platforms)
    total = len(ids)

    results: Dict[str, Tuple[Optional[float], str, float]] = {}
    overall = time.monotonic()
    for idx, pid in enumerate(ids, 1):
        cfg = platforms.get(pid) or {}
        url = cfg.get("base_url") or ""
        cls = find_crawler_class(pid)
        if not url or cls is None:
            results[pid] = (None, f"SKIP(no crawler/base_url)", DEFAULT_TIMEOUT)
            elapsed = f"{'-':>6}"
        else:
            stop = _start_progress(pid, idx, total)
            try:
                seconds = measure_once(pid, cls, url)
                results[pid] = (seconds, "OK", suggest_timeout(seconds))
                elapsed = f"{seconds:5.1f}s"
            except Exception as exc:
                results[pid] = (None, f"FAIL {type(exc).__name__}: {str(exc)[:60]}", DEFAULT_TIMEOUT)
                elapsed = f"{'-':>6}"
            finally:
                if stop is not None:
                    stop.set()
        if sys.stderr.isatty():
            _clear_progress()
        status = results[pid][1]
        suggested = results[pid][2]
        old = cfg.get("fetch_timeout")
        mark = "->" if old != suggested else "=="
        old_txt = f"{old:5.1f}" if old is not None else "  -  "
        sys.stderr.write(
            f"[{idx:>2}/{total}] {pid:<14s} {elapsed} {status:<48}{old_txt} {mark} {suggested:5.1f}s\n"
        )
        sys.stderr.flush()

    print(f"\n总耗时 {time.monotonic() - overall:.1f}s, 共 {total} 个平台。")

    if args.dry_run:
        return 0

    changed = 0
    for pid in ids:
        suggested = results[pid][2]
        if platforms[pid].get("fetch_timeout") != suggested:
            platforms[pid]["fetch_timeout"] = suggested
            changed += 1
    FLAWER_JSON.write_text(
        json.dumps({"platforms": platforms}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"写回完成: {changed} 个平台值已更新 (共 {total} 个)。")
    return 0


if __name__ == "__main__":
    sys.exit(main())