import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import CurrentUser, require_role
from app.models import UserRole
from app.schemas import CheckInIn, CheckInOut
from app.services import checkin_service

router = APIRouter(tags=["check-in"])

require_scanner = require_role(UserRole.volunteer, UserRole.organizer, UserRole.admin)


@router.post("/events/{event_id}/check-in", response_model=CheckInOut)
async def check_in(
    event_id: uuid.UUID,
    body: CheckInIn,
    user: CurrentUser = Depends(require_scanner),
    session: AsyncSession = Depends(get_session),
) -> CheckInOut:
    return CheckInOut(**await checkin_service.check_in(session, user, event_id, body.token))
