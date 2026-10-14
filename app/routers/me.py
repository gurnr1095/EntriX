from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import CurrentUser, get_current_user
from app.models import User
from app.schemas import UserOut, UserPatch

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
