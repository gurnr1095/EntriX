import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import pytest
from sqlalchemy import event

from app.config import get_settings
from app.db import engine
from app.services import cache
from tests.conftest import ORGANIZER, as_user, idem, make_category, make_event


@pytest.fixture(autouse=True)
def _cache_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "cache_enabled", True)
    monkeypatch.setattr(get_settings(), "cache_ttl_seconds", 30)


@contextmanager
def count_queries() -> Iterator[list[str]]:
    """Collect every SQL statement the app sends to Postgres while the block runs."""
    statements: list[str] = []

    def record(conn: Any, cursor: Any, statement: str, *_: Any) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)


async def _detail(client: httpx.AsyncClient, event_id: str) -> httpx.Response:
    return await client.get(f"/events/{event_id}")


async def test_event_detail_is_cached_and_a_hit_never_touches_the_database(
    client: httpx.AsyncClient, open_category: dict[str, Any]
) -> None:
    eid = open_category["event_id"]

    miss = await _detail(client, eid)
    assert miss.status_code == 200 and miss.headers["X-Cache"] == "MISS"

    with count_queries() as queries:
        hit = await _detail(client, eid)
    assert hit.headers["X-Cache"] == "HIT"
    assert queries == []  # served entirely from the cache
    assert hit.content == miss.content
    assert hit.json()["categories"][0]["seats_left"] == 50


async def test_cached_and_uncached_responses_are_identical(
    client: httpx.AsyncClient, open_category: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    eid = open_category["event_id"]
    cached = (await _detail(client, eid)).json()
    monkeypatch.setattr(get_settings(), "cache_enabled", False)
    fresh = await _detail(client, eid)
    assert fresh.headers["X-Cache"] == "MISS"
    assert fresh.json() == cached


async def test_event_list_is_cached_per_page(client: httpx.AsyncClient) -> None:
    for _ in range(3):
        await make_event(client)
    first = await client.get("/events", params={"limit": 2})
    assert first.headers["X-Cache"] == "MISS"
    assert (await client.get("/events", params={"limit": 2})).headers["X-Cache"] == "HIT"
    other_page = await client.get("/events", params={"limit": 2, "cursor": first.json()["next_cursor"]})
    assert other_page.headers["X-Cache"] == "MISS"  # a different page is a different key
    assert len(other_page.json()["items"]) == 1


async def test_misses_are_not_cached_so_a_published_event_appears_at_once(
    client: httpx.AsyncClient,
) -> None:
    draft = await make_event(client, publish=False)
    assert (await _detail(client, draft["id"])).status_code == 404
    assert (await _detail(client, draft["id"])).status_code == 404  # the 404 was not stored

    await client.patch(f"/events/{draft['id']}", json={"status": "published"}, headers=ORGANIZER)
    assert (await _detail(client, draft["id"])).status_code == 200


async def test_organizer_edits_invalidate_the_event(
    client: httpx.AsyncClient, open_category: dict[str, Any]
) -> None:
    eid, cid = open_category["event_id"], open_category["id"]
    await _detail(client, eid)  # warm the cache
    assert (await _detail(client, eid)).headers["X-Cache"] == "HIT"

    r = await client.patch(f"/events/{eid}", json={"name": "Renamed"}, headers=ORGANIZER)
    assert r.status_code == 200
    after_event_edit = await _detail(client, eid)
    assert after_event_edit.headers["X-Cache"] == "MISS" and after_event_edit.json()["name"] == "Renamed"

    r = await client.patch(f"/categories/{cid}", json={"capacity": 60}, headers=ORGANIZER)
    assert r.status_code == 200
    after_category_edit = await _detail(client, eid)
    assert after_category_edit.headers["X-Cache"] == "MISS"
    assert after_category_edit.json()["categories"][0]["capacity"] == 60

    await make_category(client, eid, capacity=5, name="Brand New")
    after_new_category = await _detail(client, eid)
    assert after_new_category.headers["X-Cache"] == "MISS"
    assert len(after_new_category.json()["categories"]) == 2


async def test_seats_left_lags_by_at_most_the_ttl_but_registration_stays_correct(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The documented trade-off: browse data may be a few seconds old; booking never is."""
    monkeypatch.setattr(get_settings(), "cache_ttl_seconds", 1)
    event_row = await make_event(client)
    cat = await make_category(client, event_row["id"], capacity=1, waitlist_enabled=False)

    assert (await _detail(client, event_row["id"])).json()["categories"][0]["seats_left"] == 1
    r = await client.post(
        f"/categories/{cat['id']}/registrations", headers={**as_user("a@test.dev"), **idem()}
    )
    assert r.status_code == 201

    stale = await _detail(client, event_row["id"])
    assert stale.headers["X-Cache"] == "HIT" and stale.json()["categories"][0]["seats_left"] == 1

    # The stale page says a seat is left, but the booking path asks the database: no overbooking.
    second = await client.post(
        f"/categories/{cat['id']}/registrations", headers={**as_user("b@test.dev"), **idem()}
    )
    assert second.status_code == 409 and second.json()["error"]["code"] == "category_full"

    await asyncio.sleep(1.2)
    fresh = await _detail(client, event_row["id"])
    assert fresh.headers["X-Cache"] == "MISS" and fresh.json()["categories"][0]["seats_left"] == 0


async def test_cache_can_be_switched_off(
    client: httpx.AsyncClient, open_category: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "cache_enabled", False)
    eid = open_category["event_id"]
    assert (await _detail(client, eid)).headers["X-Cache"] == "MISS"
    assert (await _detail(client, eid)).headers["X-Cache"] == "MISS"


async def test_a_broken_cache_costs_speed_not_correctness(
    client: httpx.AsyncClient, open_category: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    class Broken:
        async def get(self, *_: Any) -> Any:
            raise ConnectionError("redis is down")

        async def set(self, *_: Any) -> Any:
            raise ConnectionError("redis is down")

        async def delete(self, *_: Any) -> Any:
            raise ConnectionError("redis is down")

    monkeypatch.setattr(cache, "_backend", lambda: Broken())
    eid = open_category["event_id"]
    r = await _detail(client, eid)
    assert r.status_code == 200 and r.headers["X-Cache"] == "MISS"
    # Organizer edits also still work when invalidation fails.
    assert (await client.patch(f"/events/{eid}", json={"name": "Still works"}, headers=ORGANIZER)).status_code == 200
