import csv
import io
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal, get_session
from app.deps import CurrentUser, require_organizer
from app.errors import AppError
from app.models import Category, Event, Registration, RegistrationStatus, Team, User
from app.routers.events import decode_cursor, encode_cursor
from app.schemas import (
    CategoryStats,
    EventStats,
    ParticipantOut,
    RegistrationRow,
    RegistrationRowPage,
)

router = APIRouter(tags=["organizer"])

CSV_COLUMNS = [
    "registration_id",
    "status",
    "category",
    "team",
    "name",
    "email",
    "college",
    "roll_no",
    "phone",
    "registered_at",
    "waitlisted_at",
]
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value: object) -> str:
    """Neutralise spreadsheet formulas: a cell starting with = + - @ would be executed."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_PREFIXES) else text


async def _require_event(session: AsyncSession, event_id: uuid.UUID) -> Event:
    event = await session.get(Event, event_id)
    if event is None:
        raise AppError(404, "not_found", "Event not found")
    return event


def _rows_query(
    event_id: uuid.UUID, category_id: uuid.UUID | None, status: RegistrationStatus | None
) -> Select[tuple[Registration, User, str, str | None]]:
    stmt = (
        select(Registration, User, Category.name, Team.name)
        .join(Category, Category.id == Registration.category_id)
        .join(User, User.id == Registration.user_id)
        .outerjoin(Team, Team.id == Registration.team_id)
        .where(Category.event_id == event_id)
    )
    if category_id is not None:
        stmt = stmt.where(Registration.category_id == category_id)
    if status is not None:
        stmt = stmt.where(Registration.status == status)
    return stmt.order_by(Registration.created_at, Registration.id)


@router.get("/events/{event_id}/registrations", response_model=RegistrationRowPage)
async def list_registrations(
    event_id: uuid.UUID,
    category_id: uuid.UUID | None = None,
    status: RegistrationStatus | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    _: CurrentUser = Depends(require_organizer),
    session: AsyncSession = Depends(get_session),
) -> RegistrationRowPage:
    await _require_event(session, event_id)
    stmt = _rows_query(event_id, category_id, status)
    if cursor:
        created_at, reg_id = decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Registration.created_at > created_at,
                and_(Registration.created_at == created_at, Registration.id > reg_id),
            )
        )
    rows = (await session.execute(stmt.limit(limit + 1))).all()
    page = rows[:limit]
    next_cursor = (
        encode_cursor(page[-1].Registration.created_at, page[-1].Registration.id)
        if len(rows) > limit
        else None
    )
    return RegistrationRowPage(
        items=[
            RegistrationRow(
                registration_id=r.Registration.id,
                status=r.Registration.status,
                category_id=r.Registration.category_id,
                category_name=r[2],
                team_name=r[3],
                participant=ParticipantOut(
                    id=r.User.id,
                    name=r.User.name,
                    email=str(r.User.email),
                    college=r.User.college,
                    roll_no=r.User.roll_no,
                    phone=r.User.phone,
                ),
                created_at=r.Registration.created_at,
                waitlisted_at=r.Registration.waitlisted_at,
            )
            for r in page
        ],
        next_cursor=next_cursor,
    )


@router.get("/events/{event_id}/registrations.csv")
async def export_registrations(
    event_id: uuid.UUID,
    category_id: uuid.UUID | None = None,
    status: RegistrationStatus | None = None,
    _: CurrentUser = Depends(require_organizer),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    event = await _require_event(session, event_id)
    stmt = _rows_query(event_id, category_id, status)

    async def lines() -> AsyncIterator[str]:
        buf = io.StringIO()
        writer = csv.writer(buf)

        def drain() -> str:
            data = buf.getvalue()
            buf.seek(0)
            buf.truncate()
            return data

        writer.writerow(CSV_COLUMNS)
        yield drain()
        # Own session: it must outlive the request handler while the body streams. Rows
        # come from a server-side cursor in chunks, so memory stays flat for big events.
        async with SessionLocal() as stream_session:
            result = await stream_session.stream(stmt.execution_options(yield_per=500))
            async for r in result:
                reg, user = r.Registration, r.User
                writer.writerow(
                    [
                        _csv_safe(v)
                        for v in (
                            reg.id,
                            reg.status.value,
                            r[2],
                            r[3],
                            user.name,
                            user.email,
                            user.college,
                            user.roll_no,
                            user.phone,
                            reg.created_at.isoformat(),
                            reg.waitlisted_at.isoformat() if reg.waitlisted_at else None,
                        )
                    ]
                )
                yield drain()

    return StreamingResponse(
        lines(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="registrations-{event.slug}.csv"'},
    )


@router.get("/events/{event_id}/stats", response_model=EventStats)
async def event_stats(
    event_id: uuid.UUID,
    _: CurrentUser = Depends(require_organizer),
    session: AsyncSession = Depends(get_session),
) -> EventStats:
    await _require_event(session, event_id)
    rows = (
        await session.execute(
            select(
                Category.id,
                Category.name,
                Category.capacity,
                Category.confirmed_count,
                func.count(Registration.id)
                .filter(Registration.status == RegistrationStatus.waitlisted)
                .label("waitlisted"),
                func.count(Registration.id)
                .filter(Registration.status == RegistrationStatus.checked_in)
                .label("checked_in"),
            )
            .outerjoin(Registration, Registration.category_id == Category.id)
            .where(Category.event_id == event_id)
            .group_by(Category.id)
            .order_by(Category.name)
        )
    ).all()
    # `confirmed` is the seat counter (confirmed + checked in), as in the SPEC example;
    # `checked_in` is the subset who have arrived.
    return EventStats(
        categories=[
            CategoryStats(
                id=r.id,
                name=r.name,
                capacity=r.capacity,
                confirmed=r.confirmed_count,
                waitlisted=r.waitlisted,
                checked_in=r.checked_in,
            )
            for r in rows
        ]
    )
