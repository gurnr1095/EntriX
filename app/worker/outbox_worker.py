"""Polls the outbox table and sends email (SPEC 4.4). Run: python -m app.worker.outbox_worker"""

import asyncio
import logging
import smtplib
import uuid
from collections.abc import Callable
from datetime import timedelta
from email.message import EmailMessage

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db import SessionLocal
from app.models import Category, Event, Outbox, OutboxStatus, Registration, User
from app.services import qr
from app.worker.emails import MailContext, build_message

log = logging.getLogger("outbox_worker")

BATCH_SIZE = 20
BACKOFF_BASE_SECONDS = 5
BACKOFF_CAP_SECONDS = 15 * 60


def backoff_seconds(attempts: int) -> int:
    """Delay before the next try after `attempts` failures: 5s, 10s, 20s ... capped."""
    return min(BACKOFF_BASE_SECONDS * 2 ** (attempts - 1), BACKOFF_CAP_SECONDS)


def smtp_send(msg: EmailMessage) -> None:
    settings = get_settings()
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        smtp.send_message(msg)


async def _load_context(session: AsyncSession, row: Outbox) -> MailContext:
    registration_id = uuid.UUID(row.payload["registration_id"])
    found = (
        await session.execute(
            select(Registration, User, Category, Event)
            .join(User, User.id == Registration.user_id)
            .join(Category, Category.id == Registration.category_id)
            .join(Event, Event.id == Category.event_id)
            .where(Registration.id == registration_id)
        )
    ).first()
    if found is None:
        raise LookupError(f"registration {registration_id} not found")
    reg, user, category, event = found
    return MailContext(
        registration_id=str(reg.id),
        status=reg.status,
        to_email=str(user.email),
        name=user.name,
        category_name=category.name,
        event_name=event.name,
        venue=event.venue,
        starts_at=event.starts_at,
        token=qr.sign(reg.id, reg.category_id),
    )


async def process_batch(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
    send: Callable[[EmailMessage], None] = smtp_send,
    *,
    max_attempts: int | None = None,
) -> int:
    """Send up to one batch of due emails. Returns how many rows were picked up.

    Rows are claimed with FOR UPDATE SKIP LOCKED, so several workers can run at once.
    """
    settings = get_settings()
    max_attempts = max_attempts or settings.outbox_max_attempts
    async with session_factory() as session, session.begin():
        rows = (
            await session.scalars(
                select(Outbox)
                .where(Outbox.status == OutboxStatus.pending, Outbox.next_attempt_at <= func.now())
                .order_by(Outbox.id)
                .with_for_update(skip_locked=True)
                .limit(BATCH_SIZE)
            )
        ).all()
        for row in rows:
            try:
                ctx = await _load_context(session, row)
                msg = build_message(row.event_type, ctx, row.id, settings.mail_from)
                if msg is not None:
                    await asyncio.to_thread(send, msg)
                row.status = OutboxStatus.sent
                row.sent_at = func.now()
            except Exception as exc:  # noqa: BLE001 - any failure means "retry later"
                row.attempts += 1
                row.last_error = f"{type(exc).__name__}: {exc}"[:1000]
                if row.attempts >= max_attempts:
                    row.status = OutboxStatus.failed
                else:
                    row.next_attempt_at = func.now() + timedelta(
                        seconds=backoff_seconds(row.attempts)
                    )
                log.warning("outbox %s failed (attempt %s): %s", row.id, row.attempts, exc)
        return len(rows)


async def run_forever() -> None:
    settings = get_settings()
    log.info("outbox worker started (poll every %ss)", settings.outbox_poll_seconds)
    while True:
        picked = await process_batch()
        if picked < BATCH_SIZE:  # a full batch means there is probably more waiting
            await asyncio.sleep(settings.outbox_poll_seconds)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(run_forever())
    except KeyboardInterrupt:
        log.info("outbox worker stopped")


if __name__ == "__main__":
    main()
