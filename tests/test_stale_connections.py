"""A database that closes idle connections (Neon suspends its compute after 5 idle minutes)
must not turn the next request into a crash.

The app keeps a pool of open connections. If the server drops them while the app is idle, the
first request after that would pick up a dead connection and fail. `pool_pre_ping` makes the
pool check a connection before handing it out, and quietly replace it if it is dead.
"""

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from tests.conftest import as_user


async def _database_drops_every_idle_connection() -> int:
    """What a suspending Neon compute does: close every connection but this one."""
    admin = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with admin.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND pid <> pg_backend_pid()"
                )
            )
            return int(result.scalar() or 0)
    finally:
        await admin.dispose()


async def test_requests_survive_the_database_dropping_pooled_connections(
    client: httpx.AsyncClient,
) -> None:
    # Warm the pool: both the request session and the separate sign-in lookup session.
    assert (await client.get("/healthz")).status_code == 200
    assert (await client.get("/me", headers=as_user("idle@test.dev"))).status_code == 200

    assert await _database_drops_every_idle_connection() >= 1  # the pool really lost something

    # The next requests must work, not crash on a dead connection.
    assert (await client.get("/healthz")).status_code == 200
    me = await client.get("/me", headers=as_user("idle@test.dev"))
    assert me.status_code == 200 and me.json()["email"] == "idle@test.dev"


async def test_the_outbox_worker_also_survives_dropped_connections(
    client: httpx.AsyncClient,
) -> None:
    from app.db import SessionLocal
    from app.worker.outbox_worker import process_batch
    from tests.test_outbox_worker import Mailbox

    await process_batch(SessionLocal, Mailbox())  # warm a pooled connection
    await _database_drops_every_idle_connection()
    assert await process_batch(SessionLocal, Mailbox()) == 0  # no crash, nothing queued
