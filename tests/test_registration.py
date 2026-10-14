import asyncio
from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy import text

from app.db import engine
from tests.conftest import as_user, idem, make_category, make_event
from tests.invariants import assert_invariants


async def _register(client: httpx.AsyncClient, category_id: str, email: str) -> httpx.Response:
    return await client.post(
        f"/categories/{category_id}/registrations", headers={**as_user(email), **idem()}
    )


async def test_1_capacity_under_concurrency(
    client: httpx.AsyncClient, open_category: dict[str, Any]
) -> None:
    """200 distinct users race for 50 seats: exactly 50 win, 150 get category_full."""
    cid = open_category["id"]
    responses = await asyncio.gather(
        *(_register(client, cid, f"user{i}@test.dev") for i in range(200))
    )

    created = [r for r in responses if r.status_code == 201]
    rejected = [r for r in responses if r.status_code == 409]
    assert len(created) == 50
    assert len(rejected) == 150
    assert {r.json()["error"]["code"] for r in rejected} == {"category_full"}
    assert {r.json()["status"] for r in created} == {"confirmed"}

    async with engine.connect() as conn:
        confirmed = await conn.scalar(
            text("SELECT count(*) FROM registrations WHERE status = 'confirmed'")
        )
        counter = await conn.scalar(
            text("SELECT confirmed_count FROM categories WHERE id = :c"), {"c": cid}
        )
        outbox = await conn.scalar(
            text("SELECT count(*) FROM outbox WHERE event_type = 'registration_confirmed'")
        )
    assert confirmed == 50
    assert counter == 50
    assert outbox == 50  # one queued email per confirmed seat, none for rejected requests
    await assert_invariants()


async def test_4_duplicate_registration_with_fresh_key(
    client: httpx.AsyncClient, open_category: dict[str, Any]
) -> None:
    cid = open_category["id"]
    first = await _register(client, cid, "dup@test.dev")
    assert first.status_code == 201

    second = await _register(client, cid, "dup@test.dev")  # new Idempotency-Key
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "already_registered"

    async with engine.connect() as conn:
        counter = await conn.scalar(
            text("SELECT confirmed_count FROM categories WHERE id = :c"), {"c": cid}
        )
    assert counter == 1  # the failed attempt did not consume a seat
    await assert_invariants()


async def test_4_concurrent_duplicates_take_one_seat(
    client: httpx.AsyncClient, open_category: dict[str, Any]
) -> None:
    cid = open_category["id"]
    responses = await asyncio.gather(*(_register(client, cid, "same@test.dev") for _ in range(10)))
    assert sorted(r.status_code for r in responses) == [201] + [409] * 9
    async with engine.connect() as conn:
        counter = await conn.scalar(
            text("SELECT confirmed_count FROM categories WHERE id = :c"), {"c": cid}
        )
    assert counter == 1
    await assert_invariants()


async def test_5_registration_window(client: httpx.AsyncClient) -> None:
    not_yet = await make_event(
        client, opens=timedelta(hours=1), closes=timedelta(hours=2)
    )
    cat_not_yet = await make_category(client, not_yet["id"], capacity=5)
    r = await _register(client, cat_not_yet["id"], "early@test.dev")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "registration_closed"

    ended = await make_event(
        client, opens=timedelta(hours=-3), closes=timedelta(hours=-2)
    )
    cat_ended = await make_category(client, ended["id"], capacity=5)
    r = await _register(client, cat_ended["id"], "late@test.dev")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "registration_closed"

    draft = await make_event(client, publish=False)
    cat_draft = await make_category(client, draft["id"], capacity=5)
    r = await _register(client, cat_draft["id"], "draft@test.dev")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "registration_closed"

    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM registrations")) == 0
        assert await conn.scalar(text("SELECT count(*) FROM outbox")) == 0
    await assert_invariants()
