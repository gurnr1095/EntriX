"""Test 14: participants cannot call organizer or volunteer endpoints, anyone can be refused
without credentials, and the right roles get through."""

import uuid
from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.db import engine
from tests.conftest import as_user, iso

ID = str(uuid.uuid4())  # nothing exists with this id, so allowed calls end in 404/409/400

ROLES: dict[str, dict[str, str] | None] = {
    "anonymous": None,
    "participant": as_user("p@test.dev"),
    "volunteer": as_user("v@test.dev", "volunteer"),
    "organizer": as_user("o@test.dev", "organizer"),
    "admin": as_user("a@test.dev", "admin"),
}

ORGANIZER_ONLY = {"organizer", "admin"}
SCANNERS = {"volunteer", "organizer", "admin"}
ANY_USER = {"participant", "volunteer", "organizer", "admin"}

EVENT_BODY = {
    "slug": "role-check",
    "name": "Role Check",
    "starts_at": "2030-01-01T10:00:00Z",
    "ends_at": "2030-01-02T10:00:00Z",
    "reg_opens_at": "2029-12-01T10:00:00Z",
    "reg_closes_at": "2029-12-31T10:00:00Z",
}
CATEGORY_BODY = {"name": "C", "sport": "s", "participation": "individual", "capacity": 3}

# (method, path, json body, extra headers, roles allowed)
ENDPOINTS: list[tuple[str, str, dict[str, Any] | None, dict[str, str], set[str]]] = [
    # organizer only
    ("POST", "/events", EVENT_BODY, {}, ORGANIZER_ONLY),
    ("PATCH", f"/events/{ID}", {"name": "x"}, {}, ORGANIZER_ONLY),
    ("POST", f"/events/{ID}/categories", CATEGORY_BODY, {}, ORGANIZER_ONLY),
    ("PATCH", f"/categories/{ID}", {"capacity": 5}, {}, ORGANIZER_ONLY),
    ("GET", f"/events/{ID}/registrations", None, {}, ORGANIZER_ONLY),
    ("GET", f"/events/{ID}/registrations.csv", None, {}, ORGANIZER_ONLY),
    ("GET", f"/events/{ID}/stats", None, {}, ORGANIZER_ONLY),
    # volunteers (and organizers) scan
    ("POST", f"/events/{ID}/check-in", {"token": "x.y"}, {}, SCANNERS),
    # any signed-in user
    ("GET", "/me", None, {}, ANY_USER),
    ("PATCH", "/me", {"college": "X"}, {}, ANY_USER),
    ("GET", "/me/registrations", None, {}, ANY_USER),
    ("POST", f"/categories/{ID}/registrations", None, {"Idempotency-Key": "k"}, ANY_USER),
    ("DELETE", f"/registrations/{ID}", None, {}, ANY_USER),
    ("GET", f"/registrations/{ID}/qr", None, {}, ANY_USER),
    ("POST", f"/categories/{ID}/teams", {"name": "T"}, {}, ANY_USER),
    ("POST", "/teams/join", {"invite_code": "ABCDEFGH"}, {}, ANY_USER),
    ("GET", f"/teams/{ID}", None, {}, ANY_USER),
    ("DELETE", f"/teams/{ID}/members/me", None, {}, ANY_USER),
    ("POST", f"/teams/{ID}/register", None, {"Idempotency-Key": "k"}, ANY_USER),
    ("DELETE", f"/teams/{ID}", None, {}, ANY_USER),
]


@pytest.mark.parametrize("role", list(ROLES))
@pytest.mark.parametrize(
    "method,path,body,extra,allowed", ENDPOINTS, ids=[f"{m} {p.replace(ID, '{id}')}" for m, p, *_ in ENDPOINTS]
)
async def test_14_role_matrix(
    client: httpx.AsyncClient,
    role: str,
    method: str,
    path: str,
    body: dict[str, Any] | None,
    extra: dict[str, str],
    allowed: set[str],
) -> None:
    headers = {**(ROLES[role] or {}), **extra}
    r = await client.request(method, path, json=body, headers=headers)

    if role in allowed:
        # Past the role check: it may fail for other reasons (nothing exists), never 401/403.
        assert r.status_code not in (401, 403), f"{role} was refused: {r.text}"
    elif role == "anonymous":
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "unauthenticated"
    else:
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "forbidden"


@pytest.mark.parametrize("path", ["/healthz", "/events", f"/events/{ID}"])
async def test_14_public_endpoints_need_no_login(client: httpx.AsyncClient, path: str) -> None:
    r = await client.get(path)
    assert r.status_code in (200, 404)  # 404 only for the unknown event id


async def test_14_a_refused_participant_changed_nothing(client: httpx.AsyncClient) -> None:
    """Being refused is not just a status code: nothing is created or modified."""
    participant = as_user("p@test.dev")
    r = await client.post("/events", json=EVENT_BODY, headers=participant)
    assert r.status_code == 403
    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM events")) == 0


async def test_14_dev_role_header_cannot_escalate_an_existing_user(client: httpx.AsyncClient) -> None:
    """X-Dev-Role only applies when the user is first created; it cannot promote anyone later."""
    first = await client.get("/me", headers=as_user("climber@test.dev"))
    assert first.json()["role"] == "participant"
    again = await client.get("/me", headers=as_user("climber@test.dev", "admin"))
    assert again.json()["role"] == "participant"
    body = {
        **EVENT_BODY,
        "starts_at": iso(timedelta(days=2)),
        "ends_at": iso(timedelta(days=3)),
        "reg_opens_at": iso(timedelta(hours=-1)),
        "reg_closes_at": iso(timedelta(days=1)),
    }
    r = await client.post("/events", json=body, headers=as_user("climber@test.dev", "organizer"))
    assert r.status_code == 403
