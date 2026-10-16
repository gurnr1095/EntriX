"""Deleting an event: allowed until anyone has registered, never after."""

import asyncio
import uuid

import httpx
from sqlalchemy import text

from app.db import engine
from tests.conftest import (
    ORGANIZER,
    as_user,
    idem,
    make_category,
    make_event,
    make_team_category,
)
from tests.invariants import assert_invariants


async def _count(sql: str, **params: object) -> int:
    async with engine.connect() as conn:
        return int(await conn.scalar(text(sql), params) or 0)


async def test_a_draft_event_is_deleted_with_its_categories(client: httpx.AsyncClient) -> None:
    draft = await make_event(client, publish=False)
    await make_category(client, draft["id"], capacity=5, name="Chess")
    await make_category(client, draft["id"], capacity=5, name="Carrom")

    r = await client.delete(f"/events/{draft['id']}", headers=ORGANIZER)
    assert r.status_code == 204 and r.content == b""

    assert (await client.get(f"/organizer/events/{draft['id']}", headers=ORGANIZER)).status_code == 404
    assert await _count("SELECT count(*) FROM events") == 0
    assert await _count("SELECT count(*) FROM categories") == 0
    assert (await client.get("/organizer/events", headers=ORGANIZER)).json() == []


async def test_a_published_event_nobody_joined_can_be_deleted_and_vanishes_from_the_public_list(
    client: httpx.AsyncClient,
) -> None:
    event = await make_event(client)
    await make_category(client, event["id"], capacity=5)
    assert len((await client.get("/events")).json()["items"]) == 1

    assert (await client.delete(f"/events/{event['id']}", headers=ORGANIZER)).status_code == 204
    assert (await client.get(f"/events/{event['id']}")).status_code == 404
    assert (await client.get("/events")).json()["items"] == []


async def test_an_event_with_a_registration_cannot_be_deleted(client: httpx.AsyncClient) -> None:
    event = await make_event(client)
    cid = (await make_category(client, event["id"], capacity=5))["id"]
    r = await client.post(
        f"/categories/{cid}/registrations", headers={**as_user("p@test.dev"), **idem()}
    )
    assert r.status_code == 201

    refused = await client.delete(f"/events/{event['id']}", headers=ORGANIZER)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "event_has_registrations"
    assert "Close it instead" in refused.json()["error"]["message"]

    # nothing was lost, and the invariants still hold
    assert await _count("SELECT count(*) FROM events") == 1
    assert await _count("SELECT count(*) FROM registrations") == 1
    await assert_invariants()


async def test_even_a_cancelled_registration_keeps_the_event(client: httpx.AsyncClient) -> None:
    """Cancelled rows are still history, so they also block deletion."""
    event = await make_event(client)
    cid = (await make_category(client, event["id"], capacity=5))["id"]
    me = as_user("p@test.dev")
    reg = (await client.post(f"/categories/{cid}/registrations", headers={**me, **idem()})).json()
    assert (await client.delete(f"/registrations/{reg['registration_id']}", headers=me)).status_code == 200

    r = await client.delete(f"/events/{event['id']}", headers=ORGANIZER)
    assert r.status_code == 409 and r.json()["error"]["code"] == "event_has_registrations"


async def test_forming_teams_are_removed_with_an_event_nobody_registered_for(
    client: httpx.AsyncClient,
) -> None:
    event = await make_event(client)
    cat = await make_team_category(client, event["id"], capacity=4, team_min=2, team_max=3)
    team = await client.post(
        f"/categories/{cat['id']}/teams", json={"name": "Hawks"}, headers=as_user("cap@test.dev")
    )
    assert team.status_code == 201
    assert await _count("SELECT count(*) FROM teams") == 1

    assert (await client.delete(f"/events/{event['id']}", headers=ORGANIZER)).status_code == 204
    assert await _count("SELECT count(*) FROM teams") == 0
    assert await _count("SELECT count(*) FROM team_members") == 0
    await assert_invariants()


async def test_only_organizers_may_delete_and_a_missing_event_is_404(
    client: httpx.AsyncClient,
) -> None:
    event = await make_event(client, publish=False)
    path = f"/events/{event['id']}"
    assert (await client.delete(path)).status_code == 401
    assert (await client.delete(path, headers=as_user("p@test.dev"))).status_code == 403
    assert (await client.delete(path, headers=as_user("v@test.dev", "volunteer"))).status_code == 403
    assert await _count("SELECT count(*) FROM events") == 1

    missing = await client.delete(f"/events/{uuid.uuid4()}", headers=ORGANIZER)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    again = await client.delete(path, headers=ORGANIZER)  # delete it for real, twice
    assert again.status_code == 204
    assert (await client.delete(path, headers=ORGANIZER)).status_code == 404


async def test_a_registration_racing_the_delete_never_leaves_a_half_deleted_event(
    client: httpx.AsyncClient,
) -> None:
    """Either the registration wins (the event stays, delete says 409) or the delete wins
    (registration says 404 and nothing is left): never an orphaned registration."""
    for _ in range(5):
        event = await make_event(client)
        cid = (await make_category(client, event["id"], capacity=5))["id"]
        register = client.post(
            f"/categories/{cid}/registrations", headers={**as_user("racer@test.dev"), **idem()}
        )
        delete = client.delete(f"/events/{event['id']}", headers=ORGANIZER)
        reg_r, del_r = await asyncio.gather(register, delete)

        assert del_r.status_code in (204, 409), del_r.text
        assert reg_r.status_code in (201, 404, 409), reg_r.text
        if del_r.status_code == 204:
            assert await _count("SELECT count(*) FROM registrations WHERE category_id = :c", c=cid) == 0
        else:
            assert reg_r.status_code == 201
            assert await _count("SELECT count(*) FROM events WHERE id = :e", e=event["id"]) == 1
        await assert_invariants()
        await client.delete(f"/events/{event['id']}", headers=ORGANIZER)
        async with engine.begin() as conn:  # clean this round's rows (registered ones block delete)
            await conn.execute(text("DELETE FROM registrations"))
            await conn.execute(text("DELETE FROM categories"))
            await conn.execute(text("DELETE FROM events"))
