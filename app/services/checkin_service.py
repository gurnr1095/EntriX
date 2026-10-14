import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import CurrentUser
from app.errors import AppError
from app.models import Category, Registration, RegistrationStatus, User
from app.services import qr


async def check_in(
    session: AsyncSession, volunteer: CurrentUser, event_id: uuid.UUID, token: str
) -> dict[str, Any]:
    """Verify a QR token and check the registration in (SPEC 4.5). Safe to scan twice."""
    registration_id, signature = qr.parse(token)
    async with session.begin():
        row = (
            await session.execute(
                select(Registration.category_id, Category.event_id, Category.name, User.name)
                .join(Category, Category.id == Registration.category_id)
                .join(User, User.id == Registration.user_id)
                .where(Registration.id == registration_id)
            )
        ).first()
        # An unknown registration looks the same as a forged signature.
        if row is None:
            raise AppError(400, "invalid_token", "Invalid token")
        category_id, category_event_id, category_name, participant_name = row

        qr.verify(registration_id, category_id, signature)
        if category_event_id != event_id:
            raise AppError(409, "wrong_event", "This registration belongs to a different event")

        # Lock the row so two simultaneous scans produce exactly one transition.
        registration = await session.scalar(
            select(Registration)
            .where(Registration.id == registration_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        assert registration is not None

        already = registration.status == RegistrationStatus.checked_in
        if registration.status == RegistrationStatus.confirmed:
            await session.execute(
                text(
                    "INSERT INTO check_ins (registration_id, checked_in_by) "
                    "VALUES (:rid, :by) ON CONFLICT DO NOTHING"
                ),
                {"rid": registration_id, "by": volunteer.id},
            )
            registration.status = RegistrationStatus.checked_in
            # confirmed_count already counts checked_in registrations: no change.
        elif not already:
            raise AppError(
                409,
                "not_confirmed",
                f"Registration is {registration.status.value}, not confirmed",
            )

    return {
        "registration_id": str(registration_id),
        "status": RegistrationStatus.checked_in.value,
        "already_checked_in": already,
        "participant": {"name": participant_name, "category": category_name},
    }
