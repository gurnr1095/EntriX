import uuid

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
from app.services.outbox import enqueue


async def register_individual(
    session: AsyncSession, user: CurrentUser, category_id: uuid.UUID
) -> Registration:
    """Claim a seat with one atomic conditional UPDATE (SPEC 4.1). One transaction."""
    async with session.begin():
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

        claimed = await session.scalar(
            text(
                "UPDATE categories SET confirmed_count = confirmed_count + 1 "
                "WHERE id = :cid AND confirmed_count < capacity RETURNING id"
            ),
            {"cid": category_id},
        )
        if claimed is None:
            # The waitlist arrives in M2; until then a full category rejects the request.
            raise AppError(409, "category_full", "This category is full")

        registration = Registration(
            category_id=category_id,
            user_id=user.id,
            status=RegistrationStatus.confirmed,
        )
        session.add(registration)
        try:
            await session.flush()
        except IntegrityError as exc:
            if "uq_active_registration" in str(exc.orig):
                raise AppError(409, "already_registered", "You are already registered") from exc
            raise
        enqueue(
            session,
            "registration_confirmed",
            {
                "registration_id": str(registration.id),
                "user_id": str(user.id),
                "category_id": str(category_id),
            },
        )
    return registration


async def cancel_registration(
    session: AsyncSession, user: CurrentUser, registration_id: uuid.UUID
) -> Registration:
    """Cancel a registration and release its seat under the category row lock (SPEC 4.2)."""
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
            await session.execute(
                update(Category)
                .where(Category.id == registration.category_id)
                .values(confirmed_count=Category.confirmed_count - 1)
            )
        enqueue(
            session,
            "registration_cancelled",
            {
                "registration_id": str(registration.id),
                "user_id": str(registration.user_id),
                "category_id": str(registration.category_id),
            },
        )
    return registration
