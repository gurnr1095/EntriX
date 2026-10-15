"""The Redis rate limiter and cache against a real Redis (like the DB tests, no fakes).

Locally these skip if Redis is not running (`docker compose up -d redis`). In CI Redis is a
service and REQUIRE_REDIS=1 turns a missing Redis into a failure instead of a skip.
"""

import asyncio
import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from app.services.cache import RedisCache
from app.services.rate_limit import RedisLimiter

REDIS_TEST_URL = os.environ.get("REDIS_TEST_URL", "redis://localhost:6379/15")


@pytest_asyncio.fixture
async def redis_client() -> AsyncIterator[Redis]:
    client = Redis.from_url(REDIS_TEST_URL, decode_responses=True, socket_connect_timeout=1)
    try:
        await client.ping()
    except Exception:
        await client.aclose()
        if os.environ.get("REQUIRE_REDIS") == "1":
            pytest.fail(f"Redis is required but not reachable at {REDIS_TEST_URL}")
        pytest.skip("Redis not running (docker compose up -d redis)")
    await client.flushdb()  # database 15 is reserved for these tests
    yield client
    await client.flushdb()
    await client.aclose()


async def test_redis_limiter_allows_up_to_the_limit(redis_client: Redis) -> None:
    limiter = RedisLimiter(redis_client)
    decisions = [await limiter.hit("rl:t", 3, 60) for _ in range(5)]
    assert [d.allowed for d in decisions] == [True, True, True, False, False]
    assert 1 <= decisions[3].retry_after <= 60
    assert (await limiter.hit("rl:other", 3, 60)).allowed
    assert 0 < await redis_client.pttl("rl:t") <= 60_000  # the key cleans itself up


async def test_redis_limiter_window_slides(redis_client: Redis) -> None:
    limiter = RedisLimiter(redis_client)
    assert (await limiter.hit("rl:slide", 2, 1)).allowed
    assert (await limiter.hit("rl:slide", 2, 1)).allowed
    assert not (await limiter.hit("rl:slide", 2, 1)).allowed
    await asyncio.sleep(1.2)
    assert (await limiter.hit("rl:slide", 2, 1)).allowed


async def test_redis_limiter_is_atomic_across_processes(redis_client: Redis) -> None:
    """Two limiter instances (as in two API processes) racing: exactly `limit` get through."""
    a, b = RedisLimiter(redis_client), RedisLimiter(redis_client)
    results = await asyncio.gather(
        *((a if i % 2 else b).hit("rl:race", 10, 60) for i in range(100))
    )
    assert sum(r.allowed for r in results) == 10
    assert await redis_client.zcard("rl:race") == 10


async def test_redis_cache_set_get_delete_and_expiry(redis_client: Redis) -> None:
    cache = RedisCache(redis_client)
    assert await cache.get("cache:x") is None
    await cache.set("cache:x", '{"a": 1}', 1)
    assert await cache.get("cache:x") == '{"a": 1}'
    await cache.delete("cache:x", "cache:never-existed")
    assert await cache.get("cache:x") is None

    await cache.set("cache:y", "v", 1)
    await asyncio.sleep(1.2)
    assert await cache.get("cache:y") is None
