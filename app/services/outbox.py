import asyncio
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models import Outbox

# Set after a transaction that queued email commits. An outbox worker running inside this
# process waits on it, so a confirmation goes out straight away instead of on the next poll.
# It is only an optimisation: the outbox table stays the source of truth, and a worker in
# another process (or no worker at all) is unaffected by it.
outbox_signal = asyncio.Event()

_NUDGE_FLAG = "outbox_nudge_registered"


def _wake_worker(_session: Session) -> None:
    outbox_signal.set()


def enqueue(session: AsyncSession, event_type: str, payload: dict[str, Any]) -> None:
    """Queue an email event inside the caller's transaction (never sends anything)."""
    session.add(Outbox(event_type=event_type, payload=payload))
    # Wake the in-process worker only once this transaction has really committed. A rollback
    # never fires after_commit, so no worker is woken for an email that will not exist.
    if not session.info.get(_NUDGE_FLAG):
        session.info[_NUDGE_FLAG] = True
        event.listen(session.sync_session, "after_commit", _wake_worker, once=True)
