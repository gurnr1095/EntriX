from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, case, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db import get_session
from app.deps import CurrentUser, get_current_user
from app.models import (
    Category,
    Event,
    Registration,
    RegistrationStatus,
    Team,
    TeamMember,
    TeamStatus,
    User,
)
from app.routers.events import decode_cursor, encode_cursor
from app.schemas import (
    MyRegistrationOut,
    MyRegistrationPage,
    MyTeamOut,
    UserOut,
    UserPatch,
)

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=UserOut)
async def get_me(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> User:
    me = await session.get(User, user.id)
    assert me is not None
    return me


@router.patch("", response_model=UserOut)
async def patch_me(
    body: UserPatch,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> User:
    async with session.begin():
        me = await session.get(User, user.id)
        assert me is not None
        for field, value in body.model_dump(exclude_unset=True).items():
            if field == "name" and value is None:
                continue
            setattr(me, field, value)
    return me


@router.get("/registrations", response_model=MyRegistrationPage)
async def my_registrations(
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = None,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MyRegistrationPage:
    other = aliased(Registration)
    ahead = (
        select(func.count())
        .select_from(other)
        .where(
            other.category_id == Registration.category_id,
            other.status == RegistrationStatus.waitlisted,
            tuple_(other.waitlisted_at, other.id)
            <= tuple_(Registration.waitlisted_at, Registration.id),
        )
        .correlate(Registration)
        .scalar_subquery()
    )
    position = case((Registration.status == RegistrationStatus.waitlisted, ahead), else_=None)

    stmt = (
        select(
            Registration, position.label("position"), Category, Event, Team.name.label("team_name")
        )
        .join(Category, Category.id == Registration.category_id)
        .join(Event, Event.id == Category.event_id)
        .outerjoin(Team, Team.id == Registration.team_id)
        .where(Registration.user_id == user.id)
    )
    if cursor:
        created_at, reg_id = decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Registration.created_at < created_at,
                and_(Registration.created_at == created_at, Registration.id < reg_id),
            )
        )
    rows = (
        await session.execute(
            stmt.order_by(Registration.created_at.desc(), Registration.id.desc()).limit(limit + 1)
        )
    ).all()
    page = rows[:limit]
    next_cursor = (
        encode_cursor(page[-1].Registration.created_at, page[-1].Registration.id)
        if len(rows) > limit
        else None
    )
    return MyRegistrationPage(
        items=[
            MyRegistrationOut(
                registration_id=r.Registration.id,
                category_id=r.Registration.category_id,
                status=r.Registration.status,
                waitlist_position=r.position,
                created_at=r.Registration.created_at,
                event_id=r.Event.id,
                event_name=r.Event.name,
                event_starts_at=r.Event.starts_at,
                venue=r.Event.venue,
                category_name=r.Category.name,
                sport=r.Category.sport,
                team_id=r.Registration.team_id,
                team_name=r.team_name,
            )
            for r in page
        ],
        next_cursor=next_cursor,
    )


@router.get("/teams", response_model=list[MyTeamOut])
async def my_teams(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[MyTeamOut]:
    """Teams I belong to (cancelled ones excluded), newest first.

    A forming team has no registration yet, so without this a captain who reloads the page
    would lose their team and invite code.
    """
    members = (
        select(TeamMember.team_id, func.count().label("n"))
        .group_by(TeamMember.team_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(Team, Category, Event, members.c.n)
            .join(TeamMember, and_(TeamMember.team_id == Team.id, TeamMember.user_id == user.id))
            .join(Category, Category.id == Team.category_id)
            .join(Event, Event.id == Category.event_id)
            .join(members, members.c.team_id == Team.id)
            .where(Team.status != TeamStatus.cancelled)
            .order_by(Team.created_at.desc(), Team.id.desc())
        )
    ).all()
    return [
        MyTeamOut(
            id=team.id,
            name=team.name,
            status=team.status,
            category_id=category.id,
            category_name=category.name,
            event_id=event.id,
            event_name=event.name,
            captain_id=team.captain_id,
            invite_code=team.invite_code if team.captain_id == user.id else None,
            member_count=count,
            team_size_min=category.team_size_min or 1,
            team_size_max=category.team_size_max or 1,
            is_captain=team.captain_id == user.id,
        )
        for team, category, event, count in rows
    ]
