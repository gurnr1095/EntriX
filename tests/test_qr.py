import asyncio
import base64
import hashlib
import hmac
import uuid
from typing import Any

import httpx
from sqlalchemy import text

from app.db import engine
from app.services import qr
from tests.conftest import ORGANIZER, as_user, idem, make_category, make_event
from tests.invariants import assert_invariants

VOLUNTEER = as_user("volunteer@test.dev", "volunteer")


async def _register(client: httpx.AsyncClient, cid: str, email: str) -> str:
    r = await client.post(f"/categories/{cid}/registrations", headers={**as_user(email), **idem()})
    assert r.status_code == 201, r.text
    return str(r.json()["registration_id"])


async def _token(client: httpx.AsyncClient, reg_id: str, email: str) -> str:
    r = await client.get(f"/registrations/{reg_id}/qr", headers=as_user(email))
    assert r.status_code == 200, r.text
    return str(r.json()["token"])


async def _scan(
    client: httpx.AsyncClient, event_id: str, token: str, headers: dict[str, str] = VOLUNTEER
) -> httpx.Response:
    return await client.post(f"/events/{event_id}/check-in", json={"token": token}, headers=headers)


async def _scalar(sql: str) -> int:
    async with engine.connect() as conn:
        return int(await conn.scalar(text(sql)) or 0)


async def _confirmed(client: httpx.AsyncClient, open_category: dict[str, Any]) -> tuple[str, str]:
    reg_id = await _register(client, open_category["id"], "player@test.dev")
    return reg_id, await _token(client, reg_id, "player@test.dev")


async def test_valid_scan_checks_in(
    client: httpx.AsyncClient, open_category: dict[str, Any]
) -> None:
    reg_id, token = await _confirmed(client, open_category)
    eid = open_category["event_id"]

    r = await _scan(client, eid, token)
    assert r.status_code == 200
    assert r.json() == {
        "registration_id": reg_id,
        "status": "checked_in",
        "already_checked_in": False,
        "participant": {"name": "player", "category": open_category["name"]},
    }
    assert await _scalar("SELECT count(*) FROM check_ins") == 1
    assert await _scalar("SELECT confirmed_count FROM categories") == 1  # still counts the seat
    await assert_invariants()


async def test_13_double_scan_returns_already_checked_in(
    client: httpx.AsyncClient, open_category: dict[str, Any]
) -> None:
    _, token = await _confirmed(client, open_category)
    eid = open_category["event_id"]

    first = await _scan(client, eid, token)
    second = await _scan(client, eid, token)
    assert first.json()["already_checked_in"] is False
    assert second.status_code == 200
    assert second.json()["already_checked_in"] is True
    assert await _scalar("SELECT count(*) FROM check_ins") == 1


async def test_13_simultaneous_scans_check_in_exactly_once(
    client: httpx.AsyncClient, open_category: dict[str, Any]
) -> None:
    _, token = await _confirmed(client, open_category)
    eid = open_category["event_id"]

    results = await asyncio.gather(*(_scan(client, eid, token) for _ in range(10)))
    assert {r.status_code for r in results} == {200}
    assert sorted(r.json()["already_checked_in"] for r in results) == [False] + [True] * 9
    assert await _scalar("SELECT count(*) FROM check_ins") == 1
    await assert_invariants()


async def test_13_forged_and_tampered_tokens_are_rejected(
    client: httpx.AsyncClient, open_category: dict[str, Any]
) -> None:
    reg_id, token = await _confirmed(client, open_category)
    eid = open_category["event_id"]
    category_id = open_category["id"]

    # Signed with the wrong secret (what an attacker without QR_SECRET could produce).
    digest = hmac.new(b"attacker", f"reg:{reg_id}:{category_id}".encode(), hashlib.sha256).digest()
    wrong_secret = f"{reg_id}.{base64.urlsafe_b64encode(digest).decode().rstrip('=')}"

    sig = token.split(".")[1]
    flipped = ("A" if sig[0] != "A" else "B") + sig[1:]
    other_reg = await _register(client, category_id, "other@test.dev")

    bad_tokens = {
        "wrong secret": wrong_secret,
        "tampered signature": f"{reg_id}.{flipped}",
        "bare registration id": reg_id,
        "no signature": f"{reg_id}.",
        "someone else's id, our signature": f"{other_reg}.{sig}",
        "unknown registration": f"{uuid.uuid4()}.{sig}",
        "not a uuid": f"hello.{sig}",
        "garbage": "!!!",
        "empty-ish": ".",
    }
    for label, bad in bad_tokens.items():
        r = await _scan(client, eid, bad)
        assert r.status_code == 400, label
        assert r.json()["error"]["code"] == "invalid_token", label

    assert await _scalar("SELECT count(*) FROM check_ins") == 0
    assert await _scalar("SELECT count(*) FROM registrations WHERE status = 'checked_in'") == 0


async def test_13_token_for_another_event_is_rejected(
    client: httpx.AsyncClient, open_category: dict[str, Any]
) -> None:
    _, token = await _confirmed(client, open_category)
    other_event = await make_event(client)

    r = await _scan(client, other_event["id"], token)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "wrong_event"
    assert await _scalar("SELECT count(*) FROM check_ins") == 0


async def test_13_waitlisted_and_cancelled_tokens_return_409(client: httpx.AsyncClient) -> None:
    event = await make_event(client)
    cid = (await make_category(client, event["id"], capacity=1))["id"]
    holder = await _register(client, cid, "holder@test.dev")
    waiting = await _register(client, cid, "waiting@test.dev")
    waiting_token = await _token(client, waiting, "waiting@test.dev")

    r = await _scan(client, event["id"], waiting_token)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "not_confirmed"
    assert "waitlisted" in r.json()["error"]["message"]

    # Cancel the waiting user's registration, then try the (still validly signed) token.
    await client.delete(f"/registrations/{waiting}", headers=as_user("waiting@test.dev"))
    r = await _scan(client, event["id"], waiting_token)
    assert r.status_code == 409
    assert "cancelled" in r.json()["error"]["message"]

    holder_token = await _token(client, holder, "holder@test.dev")
    await client.delete(f"/registrations/{holder}", headers=as_user("holder@test.dev"))
    r = await _scan(client, event["id"], holder_token)
    assert r.status_code == 409
    assert await _scalar("SELECT count(*) FROM check_ins") == 0
    await assert_invariants()


async def test_checked_in_registration_cannot_be_cancelled(
    client: httpx.AsyncClient, open_category: dict[str, Any]
) -> None:
    reg_id, token = await _confirmed(client, open_category)
    await _scan(client, open_category["event_id"], token)

    r = await client.delete(f"/registrations/{reg_id}", headers=as_user("player@test.dev"))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "already_checked_in"
    await assert_invariants()


async def test_check_in_roles(client: httpx.AsyncClient, open_category: dict[str, Any]) -> None:
    _, token = await _confirmed(client, open_category)
    eid = open_category["event_id"]

    assert (await _scan(client, eid, token, as_user("student@test.dev"))).status_code == 403
    assert (await client.post(f"/events/{eid}/check-in", json={"token": token})).status_code == 401
    assert (await _scan(client, eid, token, ORGANIZER)).status_code == 200  # organizers may scan


async def test_qr_endpoint_is_owner_only_and_token_has_no_pii(
    client: httpx.AsyncClient, open_category: dict[str, Any]
) -> None:
    reg_id, token = await _confirmed(client, open_category)

    stranger = as_user("x@test.dev")
    assert (await client.get(f"/registrations/{reg_id}/qr", headers=stranger)).status_code == 403
    missing = f"/registrations/{uuid.uuid4()}/qr"
    assert (await client.get(missing, headers=stranger)).status_code == 404

    parsed_id, signature = qr.parse(token)
    assert str(parsed_id) == reg_id
    assert token == f"{reg_id}.{signature}"  # only the id and a signature, nothing else
    assert "player" not in token
