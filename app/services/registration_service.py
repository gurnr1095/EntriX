import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, text, update
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
    Team,
    TeamMember,
    TeamStatus,
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


async def load_category_event(
    session: AsyncSession, category_id: uuid.UUID
) -> tuple[Category, Event, datetime]:
    """Load a category with its event and the database clock (not locked)."""
    row = (
        await session.execute(
            select(Category, Event, func.now().label("db_now"))
            .join(Event, Event.id == Category.event_id)
            .where(Category.id == category_id)
        )
    ).first()
    if row is None:
        raise AppError(404, "not_found", "Category not found")
    return row.Category, row.Event, row.db_now


def ensure_registration_open(event: Event, db_now: datetime) -> None:
    if event.status != EventStatus.published or not (
        event.reg_opens_at <= db_now <= event.reg_closes_at
    ):
        raise AppError(409, "registration_closed", "Registration is not open")


async def lock_category(session: AsyncSession, category_id: uuid.UUID) -> Category:
    """Take the category row lock. Lock order everywhere: category first, then team.

    FOR NO KEY UPDATE, not FOR UPDATE: it still excludes other seat claims, cancellations
    and capacity changes (it conflicts with itself and with UPDATE), but it does not
    conflict with the FOR KEY SHARE lock Postgres takes on this row to check foreign keys
    when a registration or team_members row is inserted. With plain FOR UPDATE a team join
    (holds team lock, wants the category's FK lock) and a team registration (holds category
    lock, wants team lock) deadlocked.
    """
    category = await session.scalar(
        select(Category)
        .where(Category.id == category_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if category is None:
        raise AppError(404, "not_found", "Category not found")
    return category


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


async def _claim_or_waitlist(session: AsyncSession, category_id: uuid.UUID) -> RegistrationStatus:
    """Decide confirmed vs waitlisted with the atomic conditional UPDATE (SPEC 4.1)."""
    claimed = await session.scalar(_CLAIM_SQL, {"cid": category_id})
    if claimed is not None:
        return RegistrationStatus.confirmed
    # A failed conditional UPDATE locks nothing, so a cancellation could commit between it
    # and our waitlist insert, leaving a free seat next to a waitlisted user (invariant 3).
    # Take the category lock, then try the claim once more.
    locked = await lock_category(session, category_id)
    claimed = await session.scalar(_CLAIM_SQL, {"cid": category_id})
    if claimed is not None:
        return RegistrationStatus.confirmed
    if not locked.waitlist_enabled:
        raise AppError(409, "category_full", "This category is full")
    return RegistrationStatus.waitlisted


async def place_registration(
    session: AsyncSession,
    *,
    category_id: uuid.UUID,
    user_id: uuid.UUID,
    team_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Claim a seat (or a waitlist spot), insert the registration and queue its email.

    Shared by individual and team registration. Runs inside the caller's transaction and
    returns the response body.
    """
    status = await _claim_or_waitlist(session, category_id)
    registration = Registration(
        category_id=category_id,
        user_id=user_id,
        team_id=team_id,
        status=status,
        # clock_timestamp(), unlike now(), moves during the transaction, so it reflects
        # arrival order; the category lock taken above serializes waitlist inserts.
        waitlisted_at=func.clock_timestamp() if status == RegistrationStatus.waitlisted else None,
    )
    session.add(registration)
    try:
        await session.flush()
    except IntegrityError as exc:
        if "uq_active_registration" in str(exc.orig):
            raise AppError(409, "already_registered", "You are already registered") from exc
        raise

    body: dict[str, Any] = {"registration_id": str(registration.id), "status": status.value}
    if status == RegistrationStatus.waitlisted:
        body["waitlist_position"] = await waitlist_position(session, registration.id)
        enqueue(session, "registration_waitlisted", _payload(registration))
    else:
        enqueue(session, "registration_confirmed", _payload(registration))
    return body


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

        category, event, db_now = await load_category_event(session, category_id)
        ensure_registration_open(event, db_now)
        if category.participation != ParticipationType.individual:
            raise AppError(
                409, "not_individual_category", "This category requires a team registration"
            )

        # Friendly error even when the category is full; the unique index is still what
        # actually guarantees one active registration per user.
        existing = await session.scalar(
            select(Registration.id).where(
                Registration.category_id == category_id,
                Registration.user_id == user.id,
                Registration.status != RegistrationStatus.cancelled,
            )
        )
        if existing is not None:
            raise AppError(409, "already_registered", "You are already registered")

        body = await place_registration(session, category_id=category_id, user_id=user.id)
        await idempotency.store_response(session, user.id, idempotency_key, 201, body)
    return 201, body


async def release_team(session: AsyncSession, team_id: uuid.UUID) -> None:
    """Mark a team cancelled and free its members (SPEC 4.2 step 2).

    The category lock must already be held (lock order: category, then team).
    """
    team = await session.scalar(
        select(Team)
        .where(Team.id == team_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    assert team is not None
    team.status = TeamStatus.cancelled
    await session.execute(delete(TeamMember).where(TeamMember.team_id == team_id))


async def cancel_locked(session: AsyncSession, registration: Registration) -> None:
    """Cancel a registration, release its seat and promote the waitlist (SPEC 4.2).

    The caller holds the category lock and has locked the registration row.
    """
    if registration.status == RegistrationStatus.cancelled:
        raise AppError(409, "already_cancelled", "Registration is already cancelled")
    if registration.status == RegistrationStatus.checked_in:
        raise AppError(409, "already_checked_in", "A checked-in registration cannot be cancelled")

    was_confirmed = registration.status == RegistrationStatus.confirmed
    registration.status = RegistrationStatus.cancelled
    registration.updated_at = func.now()
    if was_confirmed:
        # The seat transfers to the oldest waitlisted registration, or is released.
        await session.flush()
        promoted = await promote_waitlist(session, registration.category_id, 1)
        if promoted == 0:
            await session.execute(
                update(Category)
                .where(Category.id == registration.category_id)
                .values(confirmed_count=Category.confirmed_count - 1)
            )
    if registration.team_id is not None:
        await release_team(session, registration.team_id)
    enqueue(session, "registration_cancelled", _payload(registration))


async def cancel_registration(
    session: AsyncSession, user: CurrentUser, registration_id: uuid.UUID
) -> Registration:
    """Cancel a registration (owner or organizer) under the category row lock."""
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
        await lock_category(session, found.category_id)
        # Re-read under the lock: a concurrent cancel may have won the race.
        registration = await session.scalar(
            select(Registration)
            .where(Registration.id == registration_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        assert registration is not None
        await cancel_locked(session, registration)
    return registration
