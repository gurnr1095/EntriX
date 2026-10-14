from typing import Any, NoReturn

import httpx
import pytest
from sqlalchemy import text

from app.db import engine
from app.services import registration_service
from tests.conftest import as_user, make_category, make_event
from tests.invariants import assert_invariants


def _boom(*_: Any, **__: Any) -> NoReturn:
    raise RuntimeError("simulated failure after the registration insert")


async def _count(sql: str) -> int:
    async with engine.connect() as conn:
        return int(await conn.scalar(text(sql)) or 0)


async def test_11_failure_after_insert_leaves_no_registration_and_no_outbox_row(
    client: httpx.AsyncClient,
    open_category: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cid = open_category["id"]
    headers = {**as_user("atomic@test.dev"), "Idempotency-Key": "atomic-1"}

    # The registration row is flushed (inserted) before enqueue runs, so this fails
    # inside the transaction, after the insert and after the seat was claimed.
    with monkeypatch.context() as patch:
        patch.setattr(registration_service, "enqueue", _boom)
        with pytest.raises(RuntimeError):
            await client.post(f"/categories/{cid}/registrations", headers=headers)

    assert await _count("SELECT count(*) FROM registrations") == 0
    assert await _count("SELECT count(*) FROM outbox") == 0
    assert await _count("SELECT count(*) FROM idempotency_keys") == 0
    assert await _count("SELECT confirmed_count FROM categories") == 0  # seat not consumed
    await assert_invariants()

    # Nothing was half-done, so the very same request now succeeds cleanly.
    ok = await client.post(f"/categories/{cid}/registrations", headers=headers)
    assert ok.status_code == 201
    assert await _count("SELECT count(*) FROM registrations") == 1
    assert await _count("SELECT count(*) FROM outbox") == 1


async def test_11_failure_during_cancel_rolls_back_the_cancellation(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    event = await make_event(client)
    cid = (await make_category(client, event["id"], capacity=2))["id"]
    reg = (
        await client.post(
            f"/categories/{cid}/registrations",
            headers={**as_user("c@test.dev"), "Idempotency-Key": "c1"},
        )
    ).json()

    with monkeypatch.context() as patch:
        patch.setattr(registration_service, "enqueue", _boom)
        with pytest.raises(RuntimeError):
            await client.delete(
                f"/registrations/{reg['registration_id']}", headers=as_user("c@test.dev")
            )

    assert await _count("SELECT count(*) FROM registrations WHERE status = 'confirmed'") == 1
    assert await _count("SELECT confirmed_count FROM categories") == 1
    cancelled_mail = "SELECT count(*) FROM outbox WHERE event_type = 'registration_cancelled'"
    assert await _count(cancelled_mail) == 0
    await assert_invariants()
