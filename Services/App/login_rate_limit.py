# -*- coding: utf-8 -*-
"""登录失败限流: Redis 共享计数优先, Redis 不可用时进程内降级。

只按客户端 IP 统计失败次数, 不把用户名放入限流键, 避免攻击者借限流
锁定特定账户。Redis 键仅保存 IP 的 sha256 摘要; 直连 Redis 不可用时,
进程内计数仍能给当前进程提供最小防护。采用滑动窗口, 反复失败不会在
固定窗口边界绕过限制。
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
import uuid
from collections import deque
from typing import Deque, Dict, Optional, Tuple

import redis

from Config.config import core_config, db_config

logger = logging.getLogger(__name__)


class LoginRateLimiter:
    """滑动窗口登录失败限流器。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._memory: Dict[str, Deque[float]] = {}
        self._redis: Optional[redis.Redis] = None
        self._redis_tried = False

    @staticmethod
    def _key(client_ip: str) -> str:
        digest = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()
        return f"auth:login:fail:{digest}"

    @staticmethod
    def _settings() -> Tuple[int, int]:
        config = core_config()["auth"]["login_rate_limit"]
        return int(config["max_attempts"]), int(config["window_seconds"])

    def _get_redis(self) -> Optional[redis.Redis]:
        if self._redis_tried:
            return self._redis
        self._redis_tried = True
        try:
            config = db_config()["redis"]
            client = redis.Redis(
                host=config["host"],
                port=config["port"],
                db=config.get("db", 0),
                password=config.get("password") or None,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
            client.ping()
            self._redis = client
        except Exception as exc:
            logger.warning("登录限流 Redis 不可用, 降级为进程内计数: %s", exc)
            self._redis = None
        return self._redis

    def _disable_redis(self, exc: Exception) -> None:
        logger.warning("登录限流 Redis 操作失败, 降级为进程内计数: %s", exc)
        self._redis = None
        self._redis_tried = True

    def _memory_limited(self, key: str, limit: int, window: int) -> Optional[int]:
        now = time.monotonic()
        cutoff = now - window
        with self._lock:
            attempts = self._memory.get(key)
            if attempts is None:
                return None
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if not attempts:
                self._memory.pop(key, None)
                return None
            if len(attempts) < limit:
                return None
            return max(1, int(attempts[0] + window - now))

    def _memory_record_failure(
        self, key: str, limit: int, window: int
    ) -> Tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - window
        with self._lock:
            attempts = self._memory.setdefault(key, deque())
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            attempts.append(now)
            if len(attempts) < limit:
                return False, 0
            return len(attempts) >= limit, max(1, int(attempts[0] + window - now))

    def is_limited(self, client_ip: str) -> Optional[int]:
        """已达失败上限时返回剩余秒数, 否则返回 None。"""
        limit, window = self._settings()
        key = self._key(client_ip)
        client = self._get_redis()
        if client is not None:
            try:
                now = time.time()
                cutoff = now - window
                client.zremrangebyscore(key, "-inf", cutoff)
                count = int(client.zcard(key))
                oldest = client.zrange(key, 0, 0, withscores=True)
                if count < limit or not oldest:
                    return None
                return max(1, int(float(oldest[0][1]) + window - now))
            except redis.RedisError as exc:
                self._disable_redis(exc)
        return self._memory_limited(key, limit, window)

    def record_failure(self, client_ip: str) -> Tuple[bool, int]:
        """记录一次失败, 返回 ``(刚进入限流, 剩余秒数)``。"""
        limit, window = self._settings()
        key = self._key(client_ip)
        client = self._get_redis()
        if client is not None:
            try:
                now = time.time()
                cutoff = now - window
                member = f"{now:.9f}:{uuid.uuid4().hex}"
                client.zremrangebyscore(key, "-inf", cutoff)
                client.zadd(key, {member: now})
                count = int(client.zcard(key))
                client.expire(key, window)
                oldest = client.zrange(key, 0, 0, withscores=True)
                if count < limit or not oldest:
                    return False, 0
                retry_after = max(1, int(float(oldest[0][1]) + window - now))
                return int(count) >= limit, retry_after
            except redis.RedisError as exc:
                self._disable_redis(exc)
        return self._memory_record_failure(key, limit, window)

    def reset(self, client_ip: str) -> None:
        """成功登录后清除该 IP 的失败计数。"""
        key = self._key(client_ip)
        client = self._get_redis()
        if client is not None:
            try:
                client.delete(key)
            except redis.RedisError as exc:
                self._disable_redis(exc)
        with self._lock:
            self._memory.pop(key, None)


login_rate_limiter = LoginRateLimiter()
