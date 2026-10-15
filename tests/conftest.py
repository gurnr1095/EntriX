import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Point the app at the test database before any app module is imported.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://sportreg:sportreg@localhost:5433/sportreg_test",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["ENV"] = "dev"
os.environ["AUTH_MODE"] = "dev"

import httpx  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TABLES = (
    "outbox, idempotency_keys, check_ins, registrations, team_members, teams, "
    "categories, events, users"
)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _schema() -> AsyncIterator[None]:
    """Fresh schema per test session, built by the real Alembic migration."""
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": TEST_DATABASE_URL},
        check=True,
    )
    yield
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _clean(_schema: None) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=120) as c:
        yield c


def as_user(email: str, role: str | None = None) -> dict[str, str]:
    headers = {"X-Dev-User": email}
    if role:
        headers["X-Dev-Role"] = role
    return headers


def idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


def iso(delta: timedelta) -> str:
    return (datetime.now(UTC) + delta).isoformat()


ORGANIZER = as_user("organizer@test.dev", "organizer")


async def make_event(
    client: httpx.AsyncClient,
    *,
    opens: timedelta = timedelta(hours=-1),
    closes: timedelta = timedelta(hours=1),
    publish: bool = True,
) -> dict[str, Any]:
    body = {
        "slug": f"event-{uuid.uuid4().hex[:10]}",
        "name": "Test Event",
        "starts_at": iso(timedelta(days=1)),
        "ends_at": iso(timedelta(days=2)),
        "reg_opens_at": iso(opens),
        "reg_closes_at": iso(closes),
    }
    r = await client.post("/events", json=body, headers=ORGANIZER)
    assert r.status_code == 201, r.text
    event = r.json()
    if publish:
        r = await client.patch(
            f"/events/{event['id']}", json={"status": "published"}, headers=ORGANIZER
        )
        assert r.status_code == 200, r.text
        event = r.json()
    return event


async def make_category(
    client: httpx.AsyncClient,
    event_id: str,
    *,
    capacity: int,
    name: str = "Table Tennis Singles",
    waitlist_enabled: bool = True,
) -> dict[str, Any]:
    r = await client.post(
        f"/events/{event_id}/categories",
        json={
            "name": name,
            "sport": "table-tennis",
            "participation": "individual",
            "capacity": capacity,
            "waitlist_enabled": waitlist_enabled,
        },
        headers=ORGANIZER,
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest_asyncio.fixture
async def open_category(client: httpx.AsyncClient) -> dict[str, Any]:
    """A published event with open registration and one category of capacity 50."""
    event = await make_event(client)
    return await make_category(client, event["id"], capacity=50)


async def make_team_category(
    client: httpx.AsyncClient,
    event_id: str,
    *,
    capacity: int,
    team_min: int = 2,
    team_max: int = 3,
    name: str = "Cricket",
    waitlist_enabled: bool = True,
) -> dict[str, Any]:
    r = await client.post(
        f"/events/{event_id}/categories",
        json={
            "name": name,
            "sport": "cricket",
            "participation": "team",
            "team_size_min": team_min,
            "team_size_max": team_max,
            "capacity": capacity,
            "waitlist_enabled": waitlist_enabled,
        },
        headers=ORGANIZER,
    )
    assert r.status_code == 201, r.text
    return r.json()
