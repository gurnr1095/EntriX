import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.deps import CurrentUser, require_role
from app.models import UserRole
from app.schemas import CheckInIn, CheckInOut
from app.services import checkin_service, rate_limit

router = APIRouter(tags=["check-in"])

require_scanner = require_role(UserRole.volunteer, UserRole.organizer, UserRole.admin)


async def scanner_rate_limit(
    request: Request, user: CurrentUser = Depends(require_scanner)
) -> None:
    """SPEC 5: check-in is limited per volunteer (a scanning line is fast, so the cap is high)."""
    await rate_limit.enforce(
        request,
        scope="checkin",
        user_id=user.id,
        user_limit=get_settings().rate_limit_checkin_per_min,
    )


@router.post(
    "/events/{event_id}/check-in",
    response_model=CheckInOut,
    dependencies=[Depends(scanner_rate_limit)],
)
async def check_in(
    event_id: uuid.UUID,
    body: CheckInIn,
    user: CurrentUser = Depends(require_scanner),
    session: AsyncSession = Depends(get_session),
) -> CheckInOut:
    return CheckInOut(**await checkin_service.check_in(session, user, event_id, body.token))
