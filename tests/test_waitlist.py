import asyncio

import httpx
from sqlalchemy import text

from app.db import engine
from tests.conftest import ORGANIZER, as_user, idem, make_category, make_event
from tests.invariants import assert_invariants


async def _register(client: httpx.AsyncClient, category_id: str, email: str) -> httpx.Response:
    return await client.post(
        f"/categories/{category_id}/registrations", headers={**as_user(email), **idem()}
    )


async def _cancel(client: httpx.AsyncClient, registration_id: str, email: str) -> httpx.Response:
    return await client.delete(f"/registrations/{registration_id}", headers=as_user(email))


async def _scalar(sql: str, **params: object) -> object:
    async with engine.connect() as conn:
        return await conn.scalar(text(sql), params)


async def _setup(client: httpx.AsyncClient, capacity: int, users: int) -> tuple[str, list[dict]]:
    """Register users one by one (so waitlist order is known); returns the category id."""
    event = await make_event(client)
    cid = (await make_category(client, event["id"], capacity=capacity))["id"]
    out = []
    for i in range(users):
        r = await _register(client, cid, f"u{i}@test.dev")
        assert r.status_code == 201
        out.append({"email": f"u{i}@test.dev", **r.json()})
    return cid, out


async def test_6_cancel_promotes_earliest_waitlisted(client: httpx.AsyncClient) -> None:
    cid, users = await _setup(client, capacity=2, users=5)
    assert [u["status"] for u in users] == ["confirmed"] * 2 + ["waitlisted"] * 3
    assert [u.get("waitlist_position") for u in users[2:]] == [1, 2, 3]

    r = await _cancel(client, users[0]["registration_id"], users[0]["email"])
    assert r.status_code == 200

    # u2 (earliest waitlisted) is promoted; u3, u4 keep their order and move up.
    mine = {
        u["email"]: (await client.get("/me/registrations", headers=as_user(u["email"]))).json()
        for u in users[2:]
    }
    assert mine["u2@test.dev"]["items"][0]["status"] == "confirmed"
    assert mine["u2@test.dev"]["items"][0]["waitlist_position"] is None
    assert mine["u3@test.dev"]["items"][0]["waitlist_position"] == 1
    assert mine["u4@test.dev"]["items"][0]["waitlist_position"] == 2

    promoted = await _scalar(
        "SELECT payload->>'registration_id' FROM outbox WHERE event_type = 'waitlist_promoted'"
    )
    assert promoted == users[2]["registration_id"]
    assert await _scalar("SELECT count(*) FROM outbox WHERE event_type = 'waitlist_promoted'") == 1
    assert (
        await _scalar("SELECT confirmed_count FROM categories WHERE id = :c", c=cid)
    ) == 2  # the seat transferred
    await assert_invariants()


async def test_cancelling_a_waitlisted_registration_changes_no_count(
    client: httpx.AsyncClient,
) -> None:
    cid, users = await _setup(client, capacity=1, users=3)
    r = await _cancel(client, users[1]["registration_id"], users[1]["email"])
    assert r.status_code == 200
    assert (await _scalar("SELECT confirmed_count FROM categories WHERE id = :c", c=cid)) == 1
    assert await _scalar("SELECT count(*) FROM outbox WHERE event_type = 'waitlist_promoted'") == 0

    # u2 is now first in line.
    page = (await client.get("/me/registrations", headers=as_user("u2@test.dev"))).json()
    assert page["items"][0]["waitlist_position"] == 1
    await assert_invariants()


async def test_6_cancel_with_empty_waitlist_releases_the_seat(client: httpx.AsyncClient) -> None:
    cid, users = await _setup(client, capacity=2, users=2)
    await _cancel(client, users[0]["registration_id"], users[0]["email"])
    assert (await _scalar("SELECT confirmed_count FROM categories WHERE id = :c", c=cid)) == 1
    await assert_invariants()


async def test_7_concurrent_cancellations_promote_distinct_users(
    client: httpx.AsyncClient,
) -> None:
    """Cancel 10 seats at once with 15 waitlisted: exactly the 10 oldest are promoted."""
    cid, users = await _setup(client, capacity=10, users=25)
    confirmed, waitlisted = users[:10], users[10:]

    results = await asyncio.gather(
        *(_cancel(client, u["registration_id"], u["email"]) for u in confirmed)
    )
    assert {r.status_code for r in results} == {200}

    async with engine.connect() as conn:
        promoted_rows = (
            await conn.execute(
                text(
                    "SELECT payload->>'registration_id' FROM outbox "
                    "WHERE event_type = 'waitlist_promoted'"
                )
            )
        ).all()
        confirmed_ids = {
            str(r[0])
            for r in (
                await conn.execute(text("SELECT id FROM registrations WHERE status = 'confirmed'"))
            ).all()
        }
        still_waiting = await conn.scalar(
            text("SELECT count(*) FROM registrations WHERE status = 'waitlisted'")
        )
        counter = await conn.scalar(
            text("SELECT confirmed_count FROM categories WHERE id = :c"), {"c": cid}
        )

    promoted_ids = [r[0] for r in promoted_rows]
    assert len(promoted_ids) == 10
    assert len(set(promoted_ids)) == 10  # nobody promoted twice
    assert set(promoted_ids) == {u["registration_id"] for u in waitlisted[:10]}  # FIFO
    assert confirmed_ids == set(promoted_ids)
    assert still_waiting == 5
    assert counter == 10
    await assert_invariants()


async def test_9_capacity_increase_promotes_in_order(client: httpx.AsyncClient) -> None:
    cid, users = await _setup(client, capacity=2, users=6)  # 2 confirmed, 4 waitlisted

    r = await client.patch(f"/categories/{cid}", json={"capacity": 5}, headers=ORGANIZER)
    assert r.status_code == 200
    assert r.json()["confirmed_count"] == 5
    assert r.json()["seats_left"] == 0

    states = [
        (await client.get("/me/registrations", headers=as_user(u["email"]))).json()["items"][0]
        for u in users
    ]
    assert [s["status"] for s in states] == ["confirmed"] * 5 + ["waitlisted"]
    assert states[5]["waitlist_position"] == 1
    assert await _scalar("SELECT count(*) FROM outbox WHERE event_type = 'waitlist_promoted'") == 3
    await assert_invariants()

    # More capacity than waitlisted people: everyone is in, seats remain.
    r = await client.patch(f"/categories/{cid}", json={"capacity": 10}, headers=ORGANIZER)
    assert r.json()["confirmed_count"] == 6
    assert r.json()["seats_left"] == 4
    await assert_invariants()


async def test_9_capacity_decrease_below_confirmed_is_rejected(client: httpx.AsyncClient) -> None:
    cid, _ = await _setup(client, capacity=4, users=6)  # 4 confirmed, 2 waitlisted
    r = await client.patch(f"/categories/{cid}", json={"capacity": 3}, headers=ORGANIZER)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "capacity_below_confirmed"
    assert (await _scalar("SELECT capacity FROM categories WHERE id = :c", c=cid)) == 4
    # Decreasing to exactly the confirmed count is fine.
    r = await client.patch(f"/categories/{cid}", json={"capacity": 4}, headers=ORGANIZER)
    assert r.status_code == 200
    await assert_invariants()


async def test_8_invariants_under_waitlist_churn(client: httpx.AsyncClient) -> None:
    """New registrations race with cancellations; invariant 3 must never break."""
    cid, users = await _setup(client, capacity=8, users=14)
    confirmed = [u for u in users if u["status"] == "confirmed"]

    cancels = [_cancel(client, u["registration_id"], u["email"]) for u in confirmed[:6]]
    arrivals = [_register(client, cid, f"late{i}@test.dev") for i in range(30)]
    results = await asyncio.gather(*cancels, *arrivals)
    assert {r.status_code for r in results[:6]} == {200}
    assert {r.status_code for r in results[6:]} == {201}

    assert (await _scalar("SELECT confirmed_count FROM categories WHERE id = :c", c=cid)) == 8
    await assert_invariants()


async def test_waitlist_position_is_unique_and_ordered_under_concurrency(
    client: httpx.AsyncClient,
) -> None:
    event = await make_event(client)
    cid = (await make_category(client, event["id"], capacity=1))["id"]
    await _register(client, cid, "holder@test.dev")
    results = await asyncio.gather(*(_register(client, cid, f"w{i}@test.dev") for i in range(25)))
    assert sorted(r.json()["waitlist_position"] for r in results) == list(range(1, 26))
