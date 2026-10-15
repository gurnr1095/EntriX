from functools import lru_cache

from redis.asyncio import Redis

from app.config import get_settings


@lru_cache
def get_redis() -> Redis | None:
    """The shared Redis client, or None when REDIS_URL is empty (in-memory fallbacks)."""
    url = get_settings().redis_url
    if not url:
        return None
    return Redis.from_url(url, decode_responses=True, socket_timeout=1, socket_connect_timeout=1)
