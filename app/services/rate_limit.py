"""Sliding-window rate limiting (SPEC 5): Redis in production, in-memory for tests."""

import logging
import math
import time
import uuid
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from fastapi import Request
from redis.asyncio import Redis

from app.config import get_settings
from app.errors import AppError
from app.services.redis_client import get_redis

log = logging.getLogger("rate_limit")

WINDOW_SECONDS = 60


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after: int  # seconds until a slot frees up (only meaningful when not allowed)


class Limiter(Protocol):
    async def hit(self, key: str, limit: int, window_seconds: int) -> Decision: ...


class MemoryLimiter:
    """Single-process limiter. Safe without locks: no await between read and write."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}

    async def hit(self, key: str, limit: int, window_seconds: int) -> Decision:
        now = time.monotonic()
        window = self._hits.setdefault(key, deque())
        while window and window[0] <= now - window_seconds:
            window.popleft()
        if len(window) >= limit:
            return Decision(False, max(1, math.ceil(window[0] + window_seconds - now)))
        window.append(now)
        return Decision(True, 0)

    def reset(self) -> None:
        self._hits.clear()


# One atomic step: drop old hits, count, and either refuse or record this hit. Doing it in
# a Lua script means two API processes cannot both see "9 of 10" and both let a request in.
# Time comes from the Redis server so every API instance agrees on "now".
_SLIDING_WINDOW_LUA = """
local t = redis.call('TIME')
local now = t[1] * 1000 + math.floor(t[2] / 1000)
local window = tonumber(ARGV[1]) * 1000
local limit = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now - window)
local count = redis.call('ZCARD', KEYS[1])
if count >= limit then
  local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  return {0, tonumber(oldest[2]) + window - now}
end
redis.call('ZADD', KEYS[1], now, ARGV[3])
redis.call('PEXPIRE', KEYS[1], window)
return {1, 0}
"""


class RedisLimiter:
    def __init__(self, client: Redis) -> None:
        self._script = client.register_script(_SLIDING_WINDOW_LUA)

    async def hit(self, key: str, limit: int, window_seconds: int) -> Decision:
        allowed, retry_ms = await self._script(
            keys=[key], args=[window_seconds, limit, uuid.uuid4().hex]
        )
        if allowed:
            return Decision(True, 0)
        return Decision(False, max(1, math.ceil(int(retry_ms) / 1000)))


@lru_cache
def get_limiter() -> Limiter:
    client = get_redis()
    return RedisLimiter(client) if client is not None else MemoryLimiter()


def reset_for_tests() -> None:
    limiter = get_limiter()
    if isinstance(limiter, MemoryLimiter):
        limiter.reset()


def client_ip(request: Request) -> str:
    hops = get_settings().trusted_proxy_hops
    if hops > 0:
        forwarded = request.headers.get("x-forwarded-for", "")
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if len(parts) >= hops:
            return parts[-hops]
    return request.client.host if request.client else "unknown"


async def enforce(
    request: Request,
    *,
    scope: str,
    user_id: uuid.UUID,
    user_limit: int,
    ip_limit: int | None = None,
) -> None:
    """Count this request against the user's and the IP's windows; 429 if either is full.

    If Redis is unreachable we let the request through (and log): a broken cache must not
    stop people registering. Both counters are always updated, so a refused request still
    counts, which is what makes hammering a refused endpoint unprofitable.
    """
    if not get_settings().rate_limit_enabled:
        return
    checks = [(f"rl:{scope}:user:{user_id}", user_limit)]
    if ip_limit:
        checks.append((f"rl:{scope}:ip:{client_ip(request)}", ip_limit))

    retry_after = 0
    try:
        limiter = get_limiter()
        for key, limit in checks:
            decision = await limiter.hit(key, limit, WINDOW_SECONDS)
            if not decision.allowed:
                retry_after = max(retry_after, decision.retry_after)
    except Exception:
        log.exception("rate limiter unavailable; allowing the request")
        return
    if retry_after:
        # Logged so you can check TRUSTED_PROXY_HOPS against real traffic: "ip" should be the
        # visitor's address, not your proxy's.
        log.warning(
            "rate limited scope=%s user=%s ip=%s x_forwarded_for=%r",
            scope,
            user_id,
            client_ip(request),
            request.headers.get("x-forwarded-for"),
        )
        raise AppError(
            429,
            "rate_limited",
            "Too many requests, please slow down",
            headers={"Retry-After": str(retry_after)},
        )
