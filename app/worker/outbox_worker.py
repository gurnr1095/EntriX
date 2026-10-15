"""Polls the outbox table and sends email (SPEC 4.4). Run: python -m app.worker.outbox_worker

The same loop can also run inside the API process (`RUN_WORKER_IN_API=true`), for hosting that
has no background workers; see app/main.py.
"""

import asyncio
import logging
import smtplib
import ssl
import uuid
from collections.abc import Callable
from datetime import timedelta
from email.message import EmailMessage

from sqlalchemy import extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings, validate_worker_startup
from app.db import SessionLocal
from app.models import Category, Event, Outbox, OutboxStatus, Registration, User
from app.services import qr
from app.services.outbox import outbox_signal
from app.worker.emails import MailContext, build_message
from app.worker.senders import BrevoSender, DeferredError

log = logging.getLogger("outbox_worker")

BATCH_SIZE = 20
BACKOFF_BASE_SECONDS = 5
BACKOFF_CAP_SECONDS = 15 * 60
CRASH_PAUSE_SECONDS = 5  # after an unexpected error (database asleep, network blip)

Sender = Callable[[EmailMessage], None]


def backoff_seconds(attempts: int) -> int:
    """Delay before the next try after `attempts` failures: 5s, 10s, 20s ... capped."""
    return min(BACKOFF_BASE_SECONDS * 2 ** (attempts - 1), BACKOFF_CAP_SECONDS)


def smtp_send(msg: EmailMessage) -> None:
    settings = get_settings()
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        if settings.smtp_starttls:  # encrypt before any credentials are sent (port 587)
            smtp.starttls(context=ssl.create_default_context())
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)


def get_sender() -> Sender:
    """The email transport chosen by EMAIL_BACKEND."""
    if get_settings().email_backend == "brevo":
        return BrevoSender()
    return smtp_send


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
    send: Sender | None = None,
    *,
    max_attempts: int | None = None,
) -> int:
    """Send up to one batch of due emails. Returns how many rows were picked up.

    Rows are claimed with FOR UPDATE SKIP LOCKED, so several workers can run at once.
    """
    settings = get_settings()
    max_attempts = max_attempts or settings.outbox_max_attempts
    send = send or get_sender()
    inline_qr = getattr(send, "inline_images", True)
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
        deferred_for: int | None = None
        for row in rows:
            if deferred_for is not None:
                # The provider said "not now" for an earlier row: do not hammer it with the
                # rest of the batch, just push them back by the same amount.
                row.next_attempt_at = func.now() + timedelta(seconds=deferred_for)
                continue
            try:
                ctx = await _load_context(session, row)
                msg = build_message(
                    row.event_type, ctx, row.id, settings.mail_from, inline_qr=inline_qr
                )
                if msg is not None:
                    await asyncio.to_thread(send, msg)
                row.status = OutboxStatus.sent
                row.sent_at = func.now()
            except DeferredError as exc:
                # Not this email's fault (quota, bad credentials): wait, and do not count an
                # attempt, so fixing the cause lets every queued email go out.
                deferred_for = exc.delay_seconds
                row.last_error = exc.reason[:1000]
                row.next_attempt_at = func.now() + timedelta(seconds=exc.delay_seconds)
                log.warning(
                    "outbox %s deferred for %ss without using an attempt: %s",
                    row.id,
                    exc.delay_seconds,
                    exc.reason,
                )
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


async def seconds_until_next_work(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> float | None:
    """Seconds until the earliest pending row is due (0 if due already); None if none pending."""
    async with session_factory() as session:
        seconds = await session.scalar(
            select(extract("epoch", func.min(Outbox.next_attempt_at) - func.now())).where(
                Outbox.status == OutboxStatus.pending
            )
        )
    return None if seconds is None else max(0.0, float(seconds))


async def _wait(seconds: float) -> None:
    """Sleep, but wake early if a new email is queued in this process."""
    try:
        await asyncio.wait_for(outbox_signal.wait(), timeout=seconds)
    except TimeoutError:
        pass


async def run_forever(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> None:
    settings = get_settings()
    validate_worker_startup(settings)
    send = get_sender()
    poll, idle = settings.outbox_poll_seconds, settings.outbox_idle_poll_seconds
    log.info(
        "outbox worker started (backend=%s, poll %ss, idle %ss)",
        settings.email_backend,
        poll,
        idle,
    )
    while True:
        # Clear *before* working: anything committed from now on sets it again, so a wake-up
        # that arrives mid-batch is never lost.
        outbox_signal.clear()
        try:
            picked = await process_batch(session_factory, send)
            if picked >= BATCH_SIZE:  # a full batch means there is probably more waiting
                continue
            wait = idle
            if idle > poll:  # only worth a query when we are allowed to sleep long
                due = await seconds_until_next_work(session_factory)
                if due is not None:
                    wait = min(max(due, poll), idle)
        except asyncio.CancelledError:
            raise
        except Exception:
            # The database can be asleep or unreachable for a moment; a dead worker would
            # silently stop all email, so log and carry on.
            log.exception("outbox worker iteration failed; retrying shortly")
            wait = CRASH_PAUSE_SECONDS
        await _wait(wait)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(run_forever())
    except KeyboardInterrupt:
        log.info("outbox worker stopped")


if __name__ == "__main__":
    main()
