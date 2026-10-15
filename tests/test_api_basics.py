from datetime import timedelta
from typing import Any

import httpx
import pytest

from app.config import Settings, validate_startup
from tests.conftest import ORGANIZER, as_user, idem, iso, make_category, make_event


def test_prod_refuses_dev_auth() -> None:
    with pytest.raises(RuntimeError):
        validate_startup(Settings(env="prod", auth_mode="dev"))
    clerk = {"clerk_jwks_url": "https://c.example/.well-known/jwks.json", "clerk_issuer": "https://c.example"}
    with pytest.raises(RuntimeError):  # prod also refuses the placeholder QR secret
        validate_startup(Settings(env="prod", auth_mode="clerk", **clerk))
    with pytest.raises(RuntimeError):  # clerk mode needs to know where the keys are
        validate_startup(Settings(env="prod", auth_mode="clerk", qr_secret="x" * 48))
    validate_startup(Settings(env="prod", auth_mode="clerk", qr_secret="x" * 48, **clerk))


async def test_healthz(client: httpx.AsyncClient) -> None:
    r = await client.get("/healthz")
    assert r.status_code == 200


async def test_unauthenticated_and_role_checks(client: httpx.AsyncClient) -> None:
    assert (await client.get("/me")).status_code == 401
    body = {
        "slug": "x",
        "name": "X",
        "starts_at": iso(timedelta(days=1)),
        "ends_at": iso(timedelta(days=2)),
        "reg_opens_at": iso(timedelta(hours=-1)),
        "reg_closes_at": iso(timedelta(hours=1)),
    }
    r = await client.post("/events", json=body, headers=as_user("student@test.dev"))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"


async def test_me_is_created_and_patchable(client: httpx.AsyncClient) -> None:
    me = (await client.get("/me", headers=as_user("new@test.dev"))).json()
    assert me["role"] == "participant"
    r = await client.patch("/me", json={"college": "ITUSA"}, headers=as_user("new@test.dev"))
    assert r.json()["college"] == "ITUSA"


async def test_missing_idempotency_key(
    client: httpx.AsyncClient, open_category: dict[str, Any]
) -> None:
    r = await client.post(
        f"/categories/{open_category['id']}/registrations", headers=as_user("a@test.dev")
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "missing_idempotency_key"


async def test_event_validation_and_status_flow(client: httpx.AsyncClient) -> None:
    bad = {
        "slug": "bad",
        "name": "Bad",
        "starts_at": iso(timedelta(days=2)),
        "ends_at": iso(timedelta(days=1)),
        "reg_opens_at": iso(timedelta(hours=-1)),
        "reg_closes_at": iso(timedelta(hours=1)),
    }
    assert (await client.post("/events", json=bad, headers=ORGANIZER)).status_code == 422

    event = await make_event(client, publish=False)
    assert (await client.get(f"/events/{event['id']}")).status_code == 404  # draft is hidden
    assert (await client.get("/events")).json()["items"] == []

    skip = await client.patch(
        f"/events/{event['id']}", json={"status": "closed"}, headers=ORGANIZER
    )
    assert skip.status_code == 409

    await client.patch(f"/events/{event['id']}", json={"status": "published"}, headers=ORGANIZER)
    assert len((await client.get("/events")).json()["items"]) == 1
    await client.patch(f"/events/{event['id']}", json={"status": "closed"}, headers=ORGANIZER)
    assert (await client.get("/events")).json()["items"] == []


async def test_events_cursor_pagination(client: httpx.AsyncClient) -> None:
    for _ in range(3):
        await make_event(client)
    first = (await client.get("/events", params={"limit": 2})).json()
    assert len(first["items"]) == 2 and first["next_cursor"]
    params = {"limit": 2, "cursor": first["next_cursor"]}
    second = (await client.get("/events", params=params)).json()
    assert len(second["items"]) == 1 and second["next_cursor"] is None


async def test_category_capacity_rules_and_seats_left(client: httpx.AsyncClient) -> None:
    event = await make_event(client)
    cat = await make_category(client, event["id"], capacity=3)
    for i in range(2):
        r = await client.post(
            f"/categories/{cat['id']}/registrations",
            headers={**as_user(f"u{i}@test.dev"), **idem()},
        )
        assert r.status_code == 201

    detail = (await client.get(f"/events/{event['id']}")).json()
    assert detail["categories"][0]["seats_left"] == 1

    low = await client.patch(f"/categories/{cat['id']}", json={"capacity": 1}, headers=ORGANIZER)
    assert low.status_code == 409
    assert low.json()["error"]["code"] == "capacity_below_confirmed"
    ok = await client.patch(f"/categories/{cat['id']}", json={"capacity": 2}, headers=ORGANIZER)
    assert ok.status_code == 200 and ok.json()["seats_left"] == 0

    dup = await client.post(
        f"/events/{event['id']}/categories",
        json={"name": cat["name"], "sport": "x", "participation": "individual", "capacity": 1},
        headers=ORGANIZER,
    )
    assert dup.status_code == 409


def test_worker_refuses_placeholder_qr_secret_in_prod() -> None:
    from app.config import validate_worker_startup

    with pytest.raises(RuntimeError):
        validate_worker_startup(Settings(env="prod"))
    validate_worker_startup(Settings(env="prod", qr_secret="y" * 48))
    validate_worker_startup(Settings(env="dev"))  # the placeholder is fine locally
