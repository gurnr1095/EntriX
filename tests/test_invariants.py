import asyncio
from typing import Any

import httpx
from sqlalchemy import text

from app.db import engine
from tests.conftest import ORGANIZER, as_user, idem, make_category, make_event
from tests.invariants import assert_invariants


async def _register(client: httpx.AsyncClient, category_id: str, email: str) -> httpx.Response:
    return await client.post(
        f"/categories/{category_id}/registrations", headers={**as_user(email), **idem()}
    )


async def test_invariants_hold_under_register_cancel_churn(client: httpx.AsyncClient) -> None:
    event = await make_event(client)
    cat = await make_category(client, event["id"], capacity=10, waitlist_enabled=False)
    cid = cat["id"]

    first_wave = await asyncio.gather(
        *(_register(client, cid, f"wave1-{i}@test.dev") for i in range(40))
    )
    winners = [r for r in first_wave if r.status_code == 201]
    assert len(winners) == 10
    await assert_invariants()

    # Everyone holding a seat cancels at once while a second wave tries to register.
    cancels = [
        client.delete(
            f"/registrations/{r.json()['registration_id']}", headers=as_user(f"wave1-{i}@test.dev")
        )
        for i, r in enumerate(first_wave)
        if r.status_code == 201
    ]
    second_wave = [_register(client, cid, f"wave2-{i}@test.dev") for i in range(40)]
    results = await asyncio.gather(*cancels, *second_wave)
    assert all(r.status_code == 200 for r in results[: len(cancels)])
    await assert_invariants()

    async with engine.connect() as conn:
        counter = await conn.scalar(
            text("SELECT confirmed_count FROM categories WHERE id = :c"), {"c": cid}
        )
        live = await conn.scalar(
            text("SELECT count(*) FROM registrations WHERE status = 'confirmed'")
        )
    assert counter == live <= 10


async def test_concurrent_double_cancel_releases_one_seat(
    client: httpx.AsyncClient, open_category: dict[str, Any]
) -> None:
    cid = open_category["id"]
    reg = (await _register(client, cid, "a@test.dev")).json()
    other = (await _register(client, cid, "b@test.dev")).json()

    url = f"/registrations/{reg['registration_id']}"
    results = await asyncio.gather(
        *(client.delete(url, headers=as_user("a@test.dev")) for _ in range(5))
    )
    assert sorted(r.status_code for r in results) == [200, 409, 409, 409, 409]

    async with engine.connect() as conn:
        counter = await conn.scalar(
            text("SELECT confirmed_count FROM categories WHERE id = :c"), {"c": cid}
        )
    assert counter == 1  # only b still holds a seat
    assert other["status"] == "confirmed"
    await assert_invariants()


async def test_cancel_frees_seat_and_allows_reregistration(client: httpx.AsyncClient) -> None:
    event = await make_event(client)
    cat = await make_category(client, event["id"], capacity=1, waitlist_enabled=False)
    cid = cat["id"]

    reg =(await _register(client, cid, "a@test.dev")).json()
    assert (await _register(client, cid, "b@test.dev")).status_code == 409

    r = await client.delete(
        f"/registrations/{reg['registration_id']}", headers=as_user("a@test.dev")
    )
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"

    assert (await _register(client, cid, "b@test.dev")).status_code == 201
    assert (await _register(client, cid, "a@test.dev")).status_code == 409  # full again
    await assert_invariants()

    async with engine.connect() as conn:
        cancelled_mail = await conn.scalar(
            text("SELECT count(*) FROM outbox WHERE event_type = 'registration_cancelled'")
        )
    assert cancelled_mail == 1


async def test_cancel_permissions(
    client: httpx.AsyncClient, open_category: dict[str, Any]
) -> None:
    cid = open_category["id"]
    reg = (await _register(client, cid, "owner@test.dev")).json()
    url = f"/registrations/{reg['registration_id']}"

    assert (await client.delete(url, headers=as_user("stranger@test.dev"))).status_code == 403
    assert (await client.delete(url, headers=ORGANIZER)).status_code == 200  # organizer may cancel
    await assert_invariants()
