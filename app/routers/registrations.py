import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import CurrentUser, get_current_user
from app.schemas import RegistrationOut
from app.services import registration_service

router = APIRouter(tags=["registrations"])


@router.delete("/registrations/{registration_id}", response_model=RegistrationOut)
async def cancel(
    registration_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RegistrationOut:
    registration = await registration_service.cancel_registration(session, user, registration_id)
    return RegistrationOut(registration_id=registration.id, status=registration.status)
