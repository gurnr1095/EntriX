import uuid

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import CurrentUser, get_current_user, registration_rate_limit
from app.errors import AppError
from app.models import Team
from app.routers.common import stored_json_response
from app.schemas import RegistrationOut, TeamCreate, TeamDetail, TeamJoin, TeamMemberOut, TeamOut
from app.services import idempotency, team_service

router = APIRouter(tags=["teams"])


def _team_out(team: Team, *, with_code: bool) -> TeamOut:
    return TeamOut(
        id=team.id,
        category_id=team.category_id,
        name=team.name,
        captain_id=team.captain_id,
        status=team.status,
        invite_code=team.invite_code if with_code else None,
    )


@router.post("/categories/{category_id}/teams", response_model=TeamOut, status_code=201)
async def create_team(
    category_id: uuid.UUID,
    body: TeamCreate,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TeamOut:
    team = await team_service.create_team(session, user, category_id, body.name)
    return _team_out(team, with_code=True)  # the creator is the captain


@router.post("/teams/join", response_model=TeamOut)
async def join_team(
    body: TeamJoin,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TeamOut:
    team = await team_service.join_team(session, user, body.invite_code.strip().upper())
    return _team_out(team, with_code=False)


@router.get("/teams/{team_id}", response_model=TeamDetail)
async def get_team(
    team_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TeamDetail:
    team, members, can_see_code = await team_service.team_detail(session, user, team_id)
    return TeamDetail(
        **_team_out(team, with_code=can_see_code).model_dump(),
        members=[
            TeamMemberOut(user_id=uid, name=name, is_captain=uid == team.captain_id)
            for uid, name in members
        ],
    )


@router.delete("/teams/{team_id}/members/me", status_code=204)
async def leave_team(
    team_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await team_service.leave_team(session, user, team_id)
    return Response(status_code=204)


@router.post(
    "/teams/{team_id}/register",
    response_model=RegistrationOut,
    status_code=201,
    dependencies=[Depends(registration_rate_limit)],
)
async def register_team(
    team_id: uuid.UUID,
    request: Request,
    idempotency_key: str | None = Header(default=None),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    if not idempotency_key:
        raise AppError(400, "missing_idempotency_key", "Idempotency-Key header is required")
    method, path = request.method, request.url.path
    status, body = await team_service.register_team(
        session,
        user,
        team_id,
        idempotency_key=idempotency_key,
        method=method,
        path=path,
        request_hash=idempotency.hash_request(method, path, await request.body()),
    )
    return stored_json_response(status, body)


@router.delete("/teams/{team_id}", response_model=TeamOut)
async def cancel_team(
    team_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TeamOut:
    team = await team_service.cancel_team(session, user, team_id)
    return _team_out(team, with_code=False)
