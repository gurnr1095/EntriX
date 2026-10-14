from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, case, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db import get_session
from app.deps import CurrentUser, get_current_user
from app.models import Registration, RegistrationStatus, User
from app.routers.events import decode_cursor, encode_cursor
from app.schemas import MyRegistrationOut, MyRegistrationPage, UserOut, UserPatch

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

    stmt = select(Registration, position.label("position")).where(Registration.user_id == user.id)
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
            )
            for r in page
        ],
        next_cursor=next_cursor,
    )
