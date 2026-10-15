import asyncio
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.config import get_settings
from app.db import engine
from app.services import rate_limit
from app.services.rate_limit import MemoryLimiter
from tests.conftest import (
    as_user,
    idem,
    make_category,
    make_event,
    make_team_category,
)

VOLUNTEER = as_user("volunteer@test.dev", "volunteer")


async def _register(client: httpx.AsyncClient, cid: str, email: str, **extra: str) -> httpx.Response:
    return await client.post(
        f"/categories/{cid}/registrations", headers={**as_user(email), **idem(), **extra}
    )


@pytest.fixture
def limits(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Lower the limits for one test (the conftest defaults are effectively unlimited)."""

    def apply(**values: Any) -> None:
        for name, value in values.items():
            monkeypatch.setattr(get_settings(), name, value)

    return apply


# ------------------------------------------------------------ the limiter itself


async def test_memory_limiter_counts_and_slides() -> None:
    limiter = MemoryLimiter()
    assert [(await limiter.hit("k", 2, 1)).allowed for _ in range(3)] == [True, True, False]
    refused = await limiter.hit("k", 2, 1)
    assert not refused.allowed and refused.retry_after == 1
    assert (await limiter.hit("other", 2, 1)).allowed  # keys are independent

    await asyncio.sleep(1.1)  # the window slides: old hits stop counting
    assert (await limiter.hit("k", 2, 1)).allowed


# ------------------------------------------------------------------ the API


async def test_registration_is_limited_per_user(
    client: httpx.AsyncClient, open_category: dict[str, Any], limits: Any
) -> None:
    limits(rate_limit_user_per_min=3)
    cid = open_category["id"]

    statuses = [(await _register(client, cid, "eager@test.dev")).status_code for _ in range(4)]
    assert statuses == [201, 409, 409, 429]  # refused attempts count too

    r = await _register(client, cid, "eager@test.dev")
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limited"
    assert 1 <= int(r.headers["Retry-After"]) <= 60

    assert (await _register(client, cid, "patient@test.dev")).status_code == 201  # others unaffected
    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM registrations")) == 2


async def test_registration_is_limited_per_ip(
    client: httpx.AsyncClient, open_category: dict[str, Any], limits: Any
) -> None:
    limits(rate_limit_ip_per_min=5)  # users are different, the address is not
    cid = open_category["id"]
    statuses = [(await _register(client, cid, f"u{i}@test.dev")).status_code for i in range(7)]
    assert statuses == [201] * 5 + [429] * 2


async def test_concurrent_requests_cannot_slip_past_the_limit(
    client: httpx.AsyncClient, open_category: dict[str, Any], limits: Any
) -> None:
    limits(rate_limit_user_per_min=10)
    results = await asyncio.gather(
        *(_register(client, open_category["id"], "burst@test.dev") for _ in range(50))
    )
    statuses = [r.status_code for r in results]
    assert statuses.count(429) == 40
    assert statuses.count(201) == 1 and statuses.count(409) == 9


async def test_team_registration_is_limited_too(client: httpx.AsyncClient, limits: Any) -> None:
    event = await make_event(client)
    cid = (await make_team_category(client, event["id"], capacity=5, team_min=1, team_max=2))["id"]
    team = (
        await client.post(f"/categories/{cid}/teams", json={"name": "T"}, headers=as_user("cap@test.dev"))
    ).json()
    limits(rate_limit_user_per_min=2)

    statuses = [
        (
            await client.post(
                f"/teams/{team['id']}/register", headers={**as_user("cap@test.dev"), **idem()}
            )
        ).status_code
        for _ in range(3)
    ]
    assert statuses == [201, 409, 429]


async def test_check_in_is_limited_per_volunteer(
    client: httpx.AsyncClient, open_category: dict[str, Any], limits: Any
) -> None:
    limits(rate_limit_checkin_per_min=3)
    scan = {"token": "not-a-real.token"}
    eid = open_category["event_id"]

    codes = [
        (await client.post(f"/events/{eid}/check-in", json=scan, headers=VOLUNTEER)).status_code
        for _ in range(4)
    ]
    assert codes == [400, 400, 400, 429]
    # A different volunteer has their own allowance; a participant is refused before counting.
    other = as_user("volunteer2@test.dev", "volunteer")
    assert (await client.post(f"/events/{eid}/check-in", json=scan, headers=other)).status_code == 400
    assert (
        await client.post(f"/events/{eid}/check-in", json=scan, headers=as_user("p@test.dev"))
    ).status_code == 403


async def test_client_ip_ignores_forged_forwarded_for_entries(
    client: httpx.AsyncClient, open_category: dict[str, Any], limits: Any
) -> None:
    """Behind one trusted proxy only the last X-Forwarded-For entry (added by the proxy) counts."""
    limits(trusted_proxy_hops=1, rate_limit_ip_per_min=3)
    cid = open_category["id"]

    # The attacker rotates the forgeable left-hand entry; the proxy-added entry never changes.
    statuses = [
        (await _register(client, cid, f"spoof{i}@test.dev", **{"X-Forwarded-For": f"10.0.0.{i}, 203.0.113.9"})).status_code
        for i in range(5)
    ]
    assert statuses == [201, 201, 201, 429, 429]

    # A genuinely different client (different proxy-added entry) has its own bucket.
    other = await _register(client, cid, "real@test.dev", **{"X-Forwarded-For": "1.1.1.1, 198.51.100.7"})
    assert other.status_code == 201


async def test_forwarded_for_is_ignored_unless_a_proxy_is_trusted(
    client: httpx.AsyncClient, open_category: dict[str, Any], limits: Any
) -> None:
    limits(trusted_proxy_hops=0, rate_limit_ip_per_min=2)
    cid = open_category["id"]
    statuses = [
        (await _register(client, cid, f"h{i}@test.dev", **{"X-Forwarded-For": f"8.8.8.{i}"})).status_code
        for i in range(3)
    ]
    assert statuses == [201, 201, 429]


async def test_limiter_outage_does_not_block_registration(
    client: httpx.AsyncClient, open_category: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    class Broken:
        async def hit(self, *_: Any, **__: Any) -> Any:
            raise ConnectionError("redis is down")

    monkeypatch.setattr(rate_limit, "get_limiter", lambda: Broken())
    assert (await _register(client, open_category["id"], "calm@test.dev")).status_code == 201


async def test_limiter_can_be_switched_off(
    client: httpx.AsyncClient, open_category: dict[str, Any], limits: Any
) -> None:
    limits(rate_limit_enabled=False, rate_limit_user_per_min=1)
    cid = open_category["id"]
    codes = [(await _register(client, cid, "free@test.dev")).status_code for _ in range(3)]
    assert 429 not in codes


async def test_other_endpoints_are_not_limited(
    client: httpx.AsyncClient, open_category: dict[str, Any], limits: Any
) -> None:
    limits(rate_limit_user_per_min=1, rate_limit_ip_per_min=1)
    for _ in range(5):
        assert (await client.get("/me", headers=as_user("browse@test.dev"))).status_code == 200
        assert (await client.get("/events")).status_code == 200
    _ = await make_category(client, open_category["event_id"], capacity=3, name="Another")
