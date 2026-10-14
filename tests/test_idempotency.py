import asyncio
from typing import Any

import httpx
from sqlalchemy import text

from app.db import engine
from tests.conftest import as_user, make_category, make_event
from tests.invariants import assert_invariants


async def test_2_idempotent_retry_creates_one_registration(
    client: httpx.AsyncClient, open_category: dict[str, Any]
) -> None:
    """Same user + key sent 20 times concurrently: one registration, identical responses."""
    cid = open_category["id"]
    headers = {**as_user("retry@test.dev"), "Idempotency-Key": "key-20-retries"}
    responses = await asyncio.gather(
        *(client.post(f"/categories/{cid}/registrations", headers=headers) for _ in range(20))
    )

    assert {r.status_code for r in responses} == {201}
    assert len({r.content for r in responses}) == 1  # byte-identical bodies
    assert responses[0].json()["status"] == "confirmed"

    async with engine.connect() as conn:
        regs = await conn.scalar(text("SELECT count(*) FROM registrations"))
        counter = await conn.scalar(
            text("SELECT confirmed_count FROM categories WHERE id = :c"), {"c": cid}
        )
        outbox = await conn.scalar(text("SELECT count(*) FROM outbox"))
        keys = await conn.scalar(text("SELECT count(*) FROM idempotency_keys"))
    assert regs == 1
    assert counter == 1
    assert outbox == 1  # retries queue no extra email
    assert keys == 1
    await assert_invariants()


async def test_2_sequential_replay_returns_stored_waitlist_response(
    client: httpx.AsyncClient,
) -> None:
    event = await make_event(client)
    cid = (await make_category(client, event["id"], capacity=1))["id"]
    await client.post(
        f"/categories/{cid}/registrations",
        headers={**as_user("first@test.dev"), "Idempotency-Key": "k1"},
    )
    headers = {**as_user("second@test.dev"), "Idempotency-Key": "k2"}
    first = await client.post(f"/categories/{cid}/registrations", headers=headers)
    again = await client.post(f"/categories/{cid}/registrations", headers=headers)

    assert first.status_code == again.status_code == 201
    assert first.json()["status"] == "waitlisted"
    assert first.json()["waitlist_position"] == 1
    assert first.content == again.content


async def test_2_replay_survives_registration_window_closing(
    client: httpx.AsyncClient, open_category: dict[str, Any]
) -> None:
    """A retry after the event is closed still gets the original answer."""
    cid = open_category["id"]
    headers = {**as_user("late-retry@test.dev"), "Idempotency-Key": "late"}
    first = await client.post(f"/categories/{cid}/registrations", headers=headers)
    assert first.status_code == 201

    event_id = open_category["event_id"]
    organizer = as_user("organizer@test.dev", "organizer")
    r = await client.patch(f"/events/{event_id}", json={"status": "closed"}, headers=organizer)
    assert r.status_code == 200

    again = await client.post(f"/categories/{cid}/registrations", headers=headers)
    assert again.status_code == 201
    assert again.content == first.content


async def test_3_key_reuse_on_different_path_is_rejected(client: httpx.AsyncClient) -> None:
    event = await make_event(client)
    cat_a = await make_category(client, event["id"], capacity=5, name="A")
    cat_b = await make_category(client, event["id"], capacity=5, name="B")
    headers = {**as_user("reuse@test.dev"), "Idempotency-Key": "shared-key"}

    ok = await client.post(f"/categories/{cat_a['id']}/registrations", headers=headers)
    assert ok.status_code == 201

    reuse = await client.post(f"/categories/{cat_b['id']}/registrations", headers=headers)
    assert reuse.status_code == 422
    assert reuse.json()["error"]["code"] == "idempotency_key_reuse"

    async with engine.connect() as conn:
        regs = await conn.scalar(text("SELECT count(*) FROM registrations"))
    assert regs == 1  # nothing was registered for category B
    await assert_invariants()


async def test_3_key_reuse_with_different_body_is_rejected(
    client: httpx.AsyncClient, open_category: dict[str, Any]
) -> None:
    cid = open_category["id"]
    headers = {**as_user("body@test.dev"), "Idempotency-Key": "body-key"}
    ok = await client.post(f"/categories/{cid}/registrations", json={}, headers=headers)
    assert ok.status_code == 201

    reuse = await client.post(
        f"/categories/{cid}/registrations", json={"note": "different"}, headers=headers
    )
    assert reuse.status_code == 422
    assert reuse.json()["error"]["code"] == "idempotency_key_reuse"


async def test_business_errors_do_not_consume_the_key(client: httpx.AsyncClient) -> None:
    """A rejected request rolls back, so the same key works once the problem is fixed."""
    event = await make_event(client, publish=False)
    cid = (await make_category(client, event["id"], capacity=5))["id"]
    headers = {**as_user("fix@test.dev"), "Idempotency-Key": "retry-after-fix"}

    first = await client.post(f"/categories/{cid}/registrations", headers=headers)
    assert first.status_code == 409
    assert first.json()["error"]["code"] == "registration_closed"

    organizer = as_user("organizer@test.dev", "organizer")
    await client.patch(f"/events/{event['id']}", json={"status": "published"}, headers=organizer)

    second = await client.post(f"/categories/{cid}/registrations", headers=headers)
    assert second.status_code == 201
