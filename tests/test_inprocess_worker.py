import asyncio
import time
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.config import get_settings
from app.db import SessionLocal, engine
from app.main import app
from app.services import outbox as outbox_service
from app.services import registration_service
from app.services.outbox import outbox_signal
from app.worker import outbox_worker
from tests.conftest import as_user, idem
from tests.test_outbox_worker import Mailbox


def _worker_tasks() -> list[asyncio.Task[Any]]:
    return [t for t in asyncio.all_tasks() if t.get_name() == "outbox-worker" and not t.done()]


async def _register(client: httpx.AsyncClient, cid: str, email: str) -> httpx.Response:
    return await client.post(
        f"/categories/{cid}/registrations", headers={**as_user(email), **idem()}
    )


@pytest.fixture
def free_tier(monkeypatch: pytest.MonkeyPatch) -> Mailbox:
    """The free-hosting profile: worker in the API, and a one-hour idle sleep, so the only
    thing that can send an email promptly is the wake-up after a commit."""
    settings = get_settings()
    monkeypatch.setattr(settings, "run_worker_in_api", True)
    monkeypatch.setattr(settings, "outbox_idle_poll_seconds", 3600)
    monkeypatch.setattr(settings, "outbox_poll_seconds", 0.2)
    box = Mailbox()
    monkeypatch.setattr(outbox_worker, "get_sender", lambda: box)
    return box


async def test_worker_in_the_api_sends_straight_after_a_registration(
    client: httpx.AsyncClient, open_category: dict[str, Any], free_tier: Mailbox
) -> None:
    async with app.router.lifespan_context(app):
        assert len(_worker_tasks()) == 1
        await asyncio.sleep(0.5)  # let it run once and go to sleep for an hour

        started = time.monotonic()
        r = await _register(client, open_category["id"], "quick@test.dev")
        assert r.status_code == 201
        while not free_tier.sent and time.monotonic() - started < 8:
            await asyncio.sleep(0.05)

    assert [m["To"] for m in free_tier.sent] == ["quick@test.dev"]
    assert time.monotonic() - started < 8  # nowhere near the hour-long idle sleep


async def test_the_worker_stops_cleanly_with_the_app(
    client: httpx.AsyncClient, free_tier: Mailbox
) -> None:
    async with app.router.lifespan_context(app):
        await asyncio.sleep(0.3)
        assert len(_worker_tasks()) == 1
    assert _worker_tasks() == []


async def test_no_worker_starts_unless_asked(
    client: httpx.AsyncClient, open_category: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "run_worker_in_api", False)
    box = Mailbox()
    monkeypatch.setattr(outbox_worker, "get_sender", lambda: box)
    async with app.router.lifespan_context(app):
        assert _worker_tasks() == []
        await _register(client, open_category["id"], "nobody@test.dev")
        await asyncio.sleep(0.5)
    assert box.sent == []  # the row waits in the outbox for a worker
    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM outbox WHERE status = 'pending'")) == 1


async def test_a_rolled_back_registration_does_not_wake_the_worker(
    client: httpx.AsyncClient, open_category: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    real_enqueue = outbox_service.enqueue

    def enqueue_then_fail(*args: Any, **kwargs: Any) -> None:
        real_enqueue(*args, **kwargs)
        raise RuntimeError("simulated failure before commit")

    outbox_signal.clear()
    with monkeypatch.context() as patch:
        patch.setattr(registration_service, "enqueue", enqueue_then_fail)
        with pytest.raises(RuntimeError):
            await _register(client, open_category["id"], "rollback@test.dev")
    assert not outbox_signal.is_set()  # nothing committed, so nobody to wake

    assert (await _register(client, open_category["id"], "fine@test.dev")).status_code == 201
    assert outbox_signal.is_set()  # a real commit does wake it


async def test_the_worker_sleeps_until_a_retry_is_due(
    client: httpx.AsyncClient, open_category: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """With an hour-long idle sleep, a row due in 2 seconds must still go out on time."""
    settings = get_settings()
    monkeypatch.setattr(settings, "outbox_idle_poll_seconds", 3600)
    monkeypatch.setattr(settings, "outbox_poll_seconds", 0.1)
    box = Mailbox()
    monkeypatch.setattr(outbox_worker, "get_sender", lambda: box)

    await _register(client, open_category["id"], "later@test.dev")
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE outbox SET next_attempt_at = now() + interval '2 seconds'"))

    task = asyncio.create_task(outbox_worker.run_forever())
    try:
        started = time.monotonic()
        while not box.sent and time.monotonic() - started < 10:
            await asyncio.sleep(0.1)
    finally:
        task.cancel()
    assert len(box.sent) == 1
    assert time.monotonic() - started >= 1.5  # it waited for the due time, not earlier


async def test_seconds_until_next_work(client: httpx.AsyncClient, open_category: dict[str, Any]) -> None:
    assert await outbox_worker.seconds_until_next_work(SessionLocal) is None  # empty outbox

    await _register(client, open_category["id"], "due@test.dev")
    assert await outbox_worker.seconds_until_next_work(SessionLocal) == 0  # due already

    async with engine.begin() as conn:
        await conn.execute(text("UPDATE outbox SET next_attempt_at = now() + interval '120 seconds'"))
    wait = await outbox_worker.seconds_until_next_work(SessionLocal)
    assert wait is not None and 100 < wait <= 120

    async with engine.begin() as conn:  # finished rows never count
        await conn.execute(text("UPDATE outbox SET status = 'sent'"))
    assert await outbox_worker.seconds_until_next_work(SessionLocal) is None


async def test_one_failed_iteration_does_not_kill_the_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E.g. the database was asleep for a moment: log it and carry on, never go silent."""
    settings = get_settings()
    monkeypatch.setattr(settings, "outbox_idle_poll_seconds", 0.05)
    monkeypatch.setattr(settings, "outbox_poll_seconds", 0.05)
    monkeypatch.setattr(outbox_worker, "CRASH_PAUSE_SECONDS", 0.05)
    calls: list[int] = []

    async def flaky(*_: Any, **__: Any) -> int:
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionError("database is waking up")
        return 0

    monkeypatch.setattr(outbox_worker, "process_batch", flaky)
    task = asyncio.create_task(outbox_worker.run_forever())
    try:
        started = time.monotonic()
        while len(calls) < 3 and time.monotonic() - started < 5:
            await asyncio.sleep(0.05)
    finally:
        task.cancel()
    assert len(calls) >= 3  # it kept going after the error
