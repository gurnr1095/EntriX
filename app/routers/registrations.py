import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import CurrentUser, get_current_user
from app.errors import AppError
from app.models import Registration
from app.schemas import QrOut, RegistrationOut
from app.services import qr, registration_service

router = APIRouter(tags=["registrations"])


@router.get("/registrations/{registration_id}/qr", response_model=QrOut)
async def get_qr(
    registration_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> QrOut:
    registration = await session.get(Registration, registration_id)
    if registration is None:
        raise AppError(404, "not_found", "Registration not found")
    if registration.user_id != user.id:
        raise AppError(403, "forbidden", "This is not your registration")
    return QrOut(token=qr.sign(registration.id, registration.category_id))


@router.delete("/registrations/{registration_id}", response_model=RegistrationOut)
async def cancel(
    registration_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RegistrationOut:
    registration = await registration_service.cancel_registration(session, user, registration_id)
    return RegistrationOut(registration_id=registration.id, status=registration.status)
