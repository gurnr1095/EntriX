import base64
import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.exceptions import PyJWKClientConnectionError
from sqlalchemy import text

from app import auth_clerk
from app.config import get_settings
from app.db import engine
from tests.conftest import idem, iso, make_category, make_event

ISSUER = "https://clerk.example.test"
_PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_PEM = _PRIVATE.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
)


class StubKeys:
    """Stands in for Clerk's JWKS endpoint: hands back our test public key."""

    def get_signing_key_from_jwt(self, token: str) -> Any:
        return SimpleNamespace(key=_PRIVATE.public_key())


class UnreachableKeys:
    def get_signing_key_from_jwt(self, token: str) -> Any:
        raise PyJWKClientConnectionError("clerk is down")


@pytest.fixture
def clerk_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_mode", "clerk")
    monkeypatch.setattr(settings, "clerk_issuer", ISSUER)
    monkeypatch.setattr(settings, "clerk_jwks_url", "https://clerk.example.test/jwks.json")
    monkeypatch.setattr(auth_clerk, "get_verifier", lambda: auth_clerk.ClerkVerifier(ISSUER, StubKeys()))


def make_token(key: Any = _PRIVATE, **overrides: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": "user_abc123",
        "iss": ISSUER,
        "iat": now - 5,
        "exp": now + 300,
        "email": "sam@college.edu",
        "name": "Sam Singh",
        **overrides,
    }
    claims = {k: v for k, v in claims.items() if v is not None}  # None removes a claim
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-key"})


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


async def test_valid_token_signs_the_user_in(client: httpx.AsyncClient, clerk_mode: None) -> None:
    r = await client.get("/me", headers=bearer(make_token()))
    assert r.status_code == 200
    assert (r.json()["email"], r.json()["name"], r.json()["role"]) == (
        "sam@college.edu", "Sam Singh", "participant",
    )
    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT auth_id FROM users")) == "clerk:user_abc123"

    await client.get("/me", headers=bearer(make_token()))  # same person again: no duplicate
    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM users")) == 1


async def test_name_falls_back_to_the_email_prefix(client: httpx.AsyncClient, clerk_mode: None) -> None:
    r = await client.get("/me", headers=bearer(make_token(name=None)))
    assert r.json()["name"] == "sam"


@pytest.mark.parametrize("header", [None, "", "Bearer", "Bearer   ", "Basic abc", "token-without-scheme"])
async def test_missing_or_malformed_authorization_is_401(
    client: httpx.AsyncClient, clerk_mode: None, header: str | None
) -> None:
    headers = {} if header is None else {"Authorization": header}
    r = await client.get("/me", headers=headers)
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthenticated"


async def test_bad_tokens_are_rejected(client: httpx.AsyncClient, clerk_mode: None) -> None:
    now = int(time.time())
    cases = {
        "garbage": "not.a.jwt",
        "signed by another key": make_token(_OTHER),
        "wrong issuer": make_token(iss="https://evil.example"),
        "no expiry": make_token(exp=None),
        "no subject": make_token(sub=None),
        "not yet valid": make_token(nbf=now + 3600),
    }
    for label, token in cases.items():
        r = await client.get("/me", headers=bearer(token))
        assert r.status_code == 401, label
        assert r.json()["error"]["code"] == "invalid_auth_token", label

    expired = await client.get("/me", headers=bearer(make_token(exp=now - 3600)))
    assert expired.status_code == 401 and expired.json()["error"]["code"] == "token_expired"

    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM users")) == 0  # nothing was created


async def test_algorithm_confusion_and_unsigned_tokens_are_rejected(
    client: httpx.AsyncClient, clerk_mode: None
) -> None:
    """The classic JWT attacks: forge a token using only public information."""
    now = int(time.time())
    payload = _b64(json.dumps({"sub": "attacker", "iss": ISSUER, "iat": now, "exp": now + 300, "email": "a@b.co"}).encode())

    # HS256 signed with the (public) RSA key as the HMAC secret.
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": "test-key"}).encode())
    signature = _b64(hmac.new(_PUBLIC_PEM, f"{header}.{payload}".encode(), hashlib.sha256).digest())
    hs256 = f"{header}.{payload}.{signature}"

    # alg=none: no signature at all.
    none_header = _b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    unsigned = f"{none_header}.{payload}."

    for label, token in {"hs256 with public key": hs256, "alg none": unsigned}.items():
        r = await client.get("/me", headers=bearer(token))
        assert r.status_code == 401, label


async def test_token_without_an_email_claim_explains_the_fix(
    client: httpx.AsyncClient, clerk_mode: None
) -> None:
    r = await client.get("/me", headers=bearer(make_token(email=None)))
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "missing_email_claim"
    assert "Clerk session token template" in r.json()["error"]["message"]


async def test_dev_headers_are_ignored_in_clerk_mode(
    client: httpx.AsyncClient, clerk_mode: None
) -> None:
    r = await client.get("/me", headers={"X-Dev-User": "boss@test.dev", "X-Dev-Role": "admin"})
    assert r.status_code == 401
    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM users")) == 0


async def test_roles_come_from_the_database_never_the_token(
    client: httpx.AsyncClient, clerk_mode: None
) -> None:
    event_body = {
        "slug": "clerk-event", "name": "E",
        "starts_at": iso(__import__("datetime").timedelta(days=2)),
        "ends_at": iso(__import__("datetime").timedelta(days=3)),
        "reg_opens_at": iso(__import__("datetime").timedelta(hours=-1)),
        "reg_closes_at": iso(__import__("datetime").timedelta(days=1)),
    }
    # A token that *claims* to be an admin is still a participant.
    pushy = bearer(make_token(role="admin", public_metadata={"role": "admin"}))
    assert (await client.post("/events", json=event_body, headers=pushy)).status_code == 403

    # Promoting the person in the database is what grants the role.
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE users SET role = 'organizer' WHERE email = 'sam@college.edu'"))
    assert (await client.post("/events", json=event_body, headers=pushy)).status_code == 201


async def test_clerk_being_unreachable_is_503_not_401(
    client: httpx.AsyncClient, clerk_mode: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth_clerk, "get_verifier", lambda: auth_clerk.ClerkVerifier(ISSUER, UnreachableKeys()))
    r = await client.get("/me", headers=bearer(make_token()))
    assert r.status_code == 503 and r.json()["error"]["code"] == "auth_unavailable"


async def test_an_email_owned_by_another_identity_is_a_conflict(
    client: httpx.AsyncClient, clerk_mode: None
) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO users (auth_id, email, name) VALUES ('dev:sam@college.edu', 'sam@college.edu', 'old')")
        )
    r = await client.get("/me", headers=bearer(make_token()))
    assert r.status_code == 409 and r.json()["error"]["code"] == "account_conflict"


async def test_a_clerk_user_can_register_end_to_end(client: httpx.AsyncClient, clerk_mode: None) -> None:
    # Organizer-created data goes in through the dev path, then the participant uses Clerk.
    settings = get_settings()
    settings.auth_mode = "dev"
    try:
        event = await make_event(client)
        cat = await make_category(client, event["id"], capacity=2)
    finally:
        settings.auth_mode = "clerk"

    r = await client.post(
        f"/categories/{cat['id']}/registrations", headers={**bearer(make_token()), **idem()}
    )
    assert r.status_code == 201 and r.json()["status"] == "confirmed"
