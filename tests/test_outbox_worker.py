import asyncio
import uuid
from email.message import EmailMessage
from typing import Any

import httpx
from sqlalchemy import text

from app.db import SessionLocal, engine
from app.services import qr
from app.worker.outbox_worker import backoff_seconds, process_batch
from tests.conftest import as_user, idem, make_category, make_event


class Mailbox:
    """SMTP stub: records messages, optionally failing the first `fail_times` sends."""

    def __init__(self, fail_times: int = 0, always_fail: bool = False) -> None:
        self.sent: list[EmailMessage] = []
        self.calls = 0
        self.fail_times = fail_times
        self.always_fail = always_fail

    def __call__(self, msg: EmailMessage) -> None:
        self.calls += 1
        if self.always_fail or self.calls <= self.fail_times:
            raise ConnectionRefusedError("smtp is down")
        self.sent.append(msg)


async def _register(client: httpx.AsyncClient, cid: str, email: str) -> dict[str, Any]:
    r = await client.post(
        f"/categories/{cid}/registrations", headers={**as_user(email), **idem()}
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _outbox_rows() -> list[Any]:
    async with engine.connect() as conn:
        return list(
            (
                await conn.execute(
                    text(
                        "SELECT id, status, attempts, last_error, sent_at, "
                        "extract(epoch FROM next_attempt_at - now()) AS due_in "
                        "FROM outbox ORDER BY id"
                    )
                )
            ).all()
        )


async def _make_due() -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE outbox SET next_attempt_at = now() WHERE status = 'pending'")
        )


def test_backoff_grows_and_is_capped() -> None:
    assert [backoff_seconds(n) for n in (1, 2, 3, 4)] == [5, 10, 20, 40]
    assert backoff_seconds(30) == 15 * 60


async def test_12_success_marks_sent_and_email_carries_a_valid_qr(
    client: httpx.AsyncClient, open_category: dict[str, Any]
) -> None:
    reg = await _register(client, open_category["id"], "mail@test.dev")
    box = Mailbox()

    assert await process_batch(SessionLocal, box) == 1

    (row,) = await _outbox_rows()
    assert row.status == "sent" and row.sent_at is not None and row.attempts == 0

    (msg,) = box.sent
    assert msg["To"] == "mail@test.dev"
    assert msg["X-Entrix-Outbox-Id"] == str(row.id)
    assert reg["registration_id"] in msg.get_body(preferencelist=("plain",)).get_content()
    # The plain-text part carries the token; it must verify against the registration.
    token = qr.sign(uuid.UUID(reg["registration_id"]), uuid.UUID(open_category["id"]))
    assert token in msg.get_body(preferencelist=("plain",)).get_content()
    # The HTML part embeds the QR as an inline PNG.
    images = [p for p in msg.walk() if p.get_content_type() == "image/png"]
    assert len(images) == 1
    assert msg.get_content_type() == "multipart/related"
    assert images[0] in list(msg.iter_parts())  # a top-level part, so cid: lookups find it
    assert images[0].get_content().startswith(b"\x89PNG")
    assert images[0]["Content-ID"] == "<qr>"

    assert await process_batch(SessionLocal, box) == 0  # nothing left


async def test_12_failing_smtp_retries_with_growing_backoff_then_fails(
    client: httpx.AsyncClient, open_category: dict[str, Any]
) -> None:
    await _register(client, open_category["id"], "retry@test.dev")
    box = Mailbox(always_fail=True)

    delays = []
    for attempt in (1, 2):
        assert await process_batch(SessionLocal, box, max_attempts=3) == 1
        (row,) = await _outbox_rows()
        assert row.status == "pending" and row.attempts == attempt
        assert "smtp is down" in row.last_error
        delays.append(float(row.due_in))
        # Not due yet: another pass must not touch it.
        assert await process_batch(SessionLocal, box, max_attempts=3) == 0
        await _make_due()

    assert 0 < delays[0] <= 5 and 5 < delays[1] <= 10  # roughly 5s then 10s, growing

    assert await process_batch(SessionLocal, box, max_attempts=3) == 1
    (row,) = await _outbox_rows()
    assert row.status == "failed" and row.attempts == 3 and row.sent_at is None
    assert box.sent == [] and box.calls == 3

    assert await process_batch(SessionLocal, box, max_attempts=3) == 0  # failed is final


async def test_12_recovers_when_smtp_comes_back(
    client: httpx.AsyncClient, open_category: dict[str, Any]
) -> None:
    await _register(client, open_category["id"], "flaky@test.dev")
    box = Mailbox(fail_times=1)

    await process_batch(SessionLocal, box)
    await _make_due()
    await process_batch(SessionLocal, box)

    (row,) = await _outbox_rows()
    assert row.status == "sent" and row.attempts == 1
    assert len(box.sent) == 1


async def test_no_qr_email_for_a_seat_cancelled_before_sending(
    client: httpx.AsyncClient, open_category: dict[str, Any]
) -> None:
    reg = await _register(client, open_category["id"], "gone@test.dev")
    await client.delete(
        f"/registrations/{reg['registration_id']}", headers=as_user("gone@test.dev")
    )
    box = Mailbox()

    assert await process_batch(SessionLocal, box) == 2
    assert [m["Subject"].split(":")[0] for m in box.sent] == ["Registration cancelled"]
    assert {r.status for r in await _outbox_rows()} == {"sent"}


async def test_waitlist_and_promotion_emails(client: httpx.AsyncClient) -> None:
    event = await make_event(client)
    cid = (await make_category(client, event["id"], capacity=1))["id"]
    first = await _register(client, cid, "a@test.dev")
    await _register(client, cid, "b@test.dev")
    await client.delete(f"/registrations/{first['registration_id']}", headers=as_user("a@test.dev"))
    box = Mailbox()

    await process_batch(SessionLocal, box)

    subjects = [m["Subject"] for m in box.sent if m["To"] == "b@test.dev"]
    assert any(s.startswith("You're on the waitlist") for s in subjects)
    promoted = [m for m in box.sent if m["Subject"].startswith("A seat opened up")]
    assert len(promoted) == 1 and promoted[0]["To"] == "b@test.dev"
    assert any(p.get_content_type() == "image/png" for p in promoted[0].walk())


async def test_unknown_event_type_fails_instead_of_vanishing(client: httpx.AsyncClient) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO outbox (event_type, payload) VALUES "
                "('mystery', '{\"registration_id\": \"00000000-0000-0000-0000-000000000000\"}')"
            )
        )
    await process_batch(SessionLocal, Mailbox(), max_attempts=1)
    (row,) = await _outbox_rows()
    assert row.status == "failed" and row.last_error


async def test_two_workers_never_send_the_same_row_twice(
    client: httpx.AsyncClient, open_category: dict[str, Any]
) -> None:
    for i in range(30):
        await _register(client, open_category["id"], f"w{i}@test.dev")
    box = Mailbox()

    async def drain() -> None:
        while await process_batch(SessionLocal, box):
            pass

    await asyncio.gather(drain(), drain(), drain())

    assert len(box.sent) == 30
    assert len({m["X-Entrix-Outbox-Id"] for m in box.sent}) == 30
    assert {r.status for r in await _outbox_rows()} == {"sent"}
