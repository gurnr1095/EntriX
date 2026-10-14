import uuid
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import ORGANIZER_ROLES, CurrentUser
from app.errors import AppError
from app.models import (
    Category,
    Event,
    EventStatus,
    ParticipationType,
    Registration,
    RegistrationStatus,
)
from app.services import idempotency
from app.services.outbox import enqueue

_CLAIM_SQL = text(
    "UPDATE categories SET confirmed_count = confirmed_count + 1 "
    "WHERE id = :cid AND confirmed_count < capacity RETURNING id"
)


def _payload(registration: Registration) -> dict[str, str]:
    return {
        "registration_id": str(registration.id),
        "user_id": str(registration.user_id),
        "category_id": str(registration.category_id),
    }


async def waitlist_position(session: AsyncSession, registration_id: uuid.UUID) -> int:
    """1-based place in the category's waitlist, by (waitlisted_at, id)."""
    position = await session.scalar(
        text(
            "SELECT count(*) FROM registrations "
            "WHERE category_id = (SELECT category_id FROM registrations WHERE id = :rid) "
            "AND status = 'waitlisted' "
            "AND (waitlisted_at, id) <= "
            "(SELECT waitlisted_at, id FROM registrations WHERE id = :rid)"
        ),
        {"rid": registration_id},
    )
    return int(position or 0)


async def promote_waitlist(session: AsyncSession, category_id: uuid.UUID, limit: int) -> int:
    """Confirm up to `limit` oldest waitlisted registrations (SPEC 4.2).

    The caller must already hold the category row lock and must adjust
    `confirmed_count` itself (a transferred seat leaves it unchanged).
    """
    if limit <= 0:
        return 0
    rows = (
        await session.scalars(
            select(Registration)
            .where(
                Registration.category_id == category_id,
                Registration.status == RegistrationStatus.waitlisted,
            )
            .order_by(Registration.waitlisted_at, Registration.id)
            .limit(limit)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).all()
    for reg in rows:
        reg.status = RegistrationStatus.confirmed
        reg.updated_at = func.now()
        enqueue(session, "waitlist_promoted", _payload(reg))
    return len(rows)


async def register_individual(
    session: AsyncSession,
    user: CurrentUser,
    category_id: uuid.UUID,
    *,
    idempotency_key: str,
    method: str,
    path: str,
    request_hash: str,
) -> tuple[int, dict[str, Any]]:
    """Register for an individual category (SPEC 4.1). One transaction.

    Returns (http_status, body). A replayed idempotent request returns the stored pair.
    """
    async with session.begin():
        replay = await idempotency.claim(
            session, user.id, idempotency_key, method, path, request_hash
        )
        if replay is not None:
            return replay.status, replay.body

        row = (
            await session.execute(
                select(Category, Event, func.now().label("db_now"))
                .join(Event, Event.id == Category.event_id)
                .where(Category.id == category_id)
            )
        ).first()
        if row is None:
            raise AppError(404, "not_found", "Category not found")
        category, event, db_now = row.Category, row.Event, row.db_now

        if event.status != EventStatus.published or not (
            event.reg_opens_at <= db_now <= event.reg_closes_at
        ):
            raise AppError(409, "registration_closed", "Registration is not open")
        if category.participation != ParticipationType.individual:
            raise AppError(
                409, "not_individual_category", "This category requires a team registration"
            )

        # Friendly error even when the category is full; the unique index below is
        # still what actually guarantees one active registration per user.
        existing = await session.scalar(
            select(Registration.id).where(
                Registration.category_id == category_id,
                Registration.user_id == user.id,
                Registration.status != RegistrationStatus.cancelled,
            )
        )
        if existing is not None:
            raise AppError(409, "already_registered", "You are already registered")

        status = RegistrationStatus.confirmed
        claimed = await session.scalar(_CLAIM_SQL, {"cid": category_id})
        if claimed is None:
            # A failed conditional UPDATE locks nothing, so a cancellation could commit
            # between it and our waitlist insert, leaving a free seat next to a waitlisted
            # user (invariant 3). Take the category lock, then try the claim once more.
            locked = await session.scalar(
                select(Category)
                .where(Category.id == category_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            assert locked is not None
            claimed = await session.scalar(_CLAIM_SQL, {"cid": category_id})
            if claimed is None:
                if not locked.waitlist_enabled:
                    raise AppError(409, "category_full", "This category is full")
                status = RegistrationStatus.waitlisted

        registration = Registration(
            category_id=category_id,
            user_id=user.id,
            status=status,
            # clock_timestamp(), unlike now(), moves during the transaction, so it
            # reflects arrival order; the category lock above serializes waitlist inserts.
            waitlisted_at=(
                func.clock_timestamp() if status == RegistrationStatus.waitlisted else None
            ),
        )
        session.add(registration)
        try:
            await session.flush()
        except IntegrityError as exc:
            if "uq_active_registration" in str(exc.orig):
                raise AppError(409, "already_registered", "You are already registered") from exc
            raise

        body: dict[str, Any] = {
            "registration_id": str(registration.id),
            "status": status.value,
        }
        if status == RegistrationStatus.waitlisted:
            body["waitlist_position"] = await waitlist_position(session, registration.id)
            enqueue(session, "registration_waitlisted", _payload(registration))
        else:
            enqueue(session, "registration_confirmed", _payload(registration))

        await idempotency.store_response(session, user.id, idempotency_key, 201, body)
    return 201, body


async def cancel_registration(
    session: AsyncSession, user: CurrentUser, registration_id: uuid.UUID
) -> Registration:
    """Cancel a registration, release its seat and promote the waitlist (SPEC 4.2)."""
    async with session.begin():
        found = (
            await session.execute(
                select(Registration.category_id, Registration.user_id).where(
                    Registration.id == registration_id
                )
            )
        ).first()
        if found is None:
            raise AppError(404, "not_found", "Registration not found")
        if found.user_id != user.id and user.role not in ORGANIZER_ROLES:
            raise AppError(403, "forbidden", "You cannot cancel this registration")

        # Serialize with seat claims and other cancellations for this category.
        await session.execute(
            select(Category.id).where(Category.id == found.category_id).with_for_update()
        )
        # Re-read under the lock: a concurrent cancel may have won the race.
        registration = await session.scalar(
            select(Registration)
            .where(Registration.id == registration_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        assert registration is not None

        if registration.status == RegistrationStatus.cancelled:
            raise AppError(409, "already_cancelled", "Registration is already cancelled")
        if registration.status == RegistrationStatus.checked_in:
            raise AppError(
                409, "already_checked_in", "A checked-in registration cannot be cancelled"
            )

        was_confirmed = registration.status == RegistrationStatus.confirmed
        registration.status = RegistrationStatus.cancelled
        registration.updated_at = func.now()
        if was_confirmed:
            # The seat transfers to the oldest waitlisted user, or is released.
            await session.flush()
            promoted = await promote_waitlist(session, registration.category_id, 1)
            if promoted == 0:
                await session.execute(
                    update(Category)
                    .where(Category.id == registration.category_id)
                    .values(confirmed_count=Category.confirmed_count - 1)
                )
        enqueue(session, "registration_cancelled", _payload(registration))
    return registration
