from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session

router = APIRouter()


@router.get("/livez")
async def livez() -> dict[str, str]:
    """Is the process up? Touches nothing else, so a ping never wakes a sleeping database."""
    return {"status": "alive"}


@router.get("/healthz")
async def healthz(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    """Is the app *and its database* working?"""
    await session.execute(text("SELECT 1"))
    return {"status": "ok"}
