from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Outbox


def enqueue(session: AsyncSession, event_type: str, payload: dict[str, Any]) -> None:
    """Queue an email event inside the caller's transaction (never sends anything)."""
    session.add(Outbox(event_type=event_type, payload=payload))
