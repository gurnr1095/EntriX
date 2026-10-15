"""Small response cache for the public browse endpoints (SPEC M5)."""

import logging
import time
from functools import lru_cache
from typing import Protocol

from redis.asyncio import Redis

from app.config import get_settings
from app.services.redis_client import get_redis

log = logging.getLogger("cache")


class CacheBackend(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl_seconds: int) -> None: ...
    async def delete(self, *keys: str) -> None: ...


class MemoryCache:
    def __init__(self) -> None:
        self._data: dict[str, tuple[float, str]] = {}

    async def get(self, key: str) -> str | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= time.monotonic():
            self._data.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self._data[key] = (time.monotonic() + ttl_seconds, value)

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self._data.pop(key, None)

    def clear(self) -> None:
        self._data.clear()


class RedisCache:
    def __init__(self, client: Redis) -> None:
        self._client = client

    async def get(self, key: str) -> str | None:
        return await self._client.get(key)

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        await self._client.set(key, value, ex=ttl_seconds)

    async def delete(self, *keys: str) -> None:
        if keys:
            await self._client.delete(*keys)


@lru_cache
def _backend() -> CacheBackend:
    client = get_redis()
    return RedisCache(client) if client is not None else MemoryCache()


def reset_for_tests() -> None:
    backend = _backend()
    if isinstance(backend, MemoryCache):
        backend.clear()


# The functions below never raise: a cache problem costs speed, not correctness.


async def cache_get(key: str) -> str | None:
    if not get_settings().cache_enabled:
        return None
    try:
        return await _backend().get(key)
    except Exception:
        log.exception("cache read failed; falling back to the database")
        return None


async def cache_set(key: str, value: str) -> None:
    settings = get_settings()
    if not settings.cache_enabled:
        return
    try:
        await _backend().set(key, value, settings.cache_ttl_seconds)
    except Exception:
        log.exception("cache write failed")


async def cache_delete(*keys: str) -> None:
    try:
        await _backend().delete(*keys)
    except Exception:
        log.exception("cache invalidation failed")


def event_key(event_id: object) -> str:
    return f"cache:event:{event_id}"


def event_list_key(limit: int, cursor: str | None) -> str:
    return f"cache:events:list:{limit}:{cursor or ''}"
