import base64
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import CurrentUser, require_organizer
from app.errors import AppError
from app.models import Category, Event, EventStatus, Registration
from app.schemas import (
    CategoryCreate,
    CategoryOut,
    EventCreate,
    EventDetail,
    EventOut,
    EventPage,
    EventPatch,
)
from app.services import cache

router = APIRouter(tags=["events"])


def _cached_json(body: str, *, hit: bool) -> Response:
    """Browse responses say whether they came from the cache (handy for tests and load tests)."""
    return Response(
        content=body, media_type="application/json", headers={"X-Cache": "HIT" if hit else "MISS"}
    )

# draft -> published -> closed, one step at a time
_NEXT_STATUS = {
    EventStatus.draft: EventStatus.published,
    EventStatus.published: EventStatus.closed,
}


def category_out(c: Category) -> CategoryOut:
    return CategoryOut(
        id=c.id,
        event_id=c.event_id,
        name=c.name,
        sport=c.sport,
        participation=c.participation,
        team_size_min=c.team_size_min,
        team_size_max=c.team_size_max,
        capacity=c.capacity,
        confirmed_count=c.confirmed_count,
        waitlist_enabled=c.waitlist_enabled,
        seats_left=c.capacity - c.confirmed_count,
    )


def encode_cursor(starts_at: datetime, event_id: uuid.UUID) -> str:
    raw = json.dumps([starts_at.isoformat(), str(event_id)])
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        starts_at, event_id = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return datetime.fromisoformat(starts_at), uuid.UUID(event_id)
    except (ValueError, TypeError):
        raise AppError(422, "invalid_cursor", "Malformed cursor") from None


@router.post("/events", response_model=EventOut, status_code=201)
async def create_event(
    body: EventCreate,
    user: CurrentUser = Depends(require_organizer),
    session: AsyncSession = Depends(get_session),
) -> Event:
    event = Event(**body.model_dump(), created_by=user.id)
    try:
        async with session.begin():
            session.add(event)
            await session.flush()
    except IntegrityError as exc:
        if "events_slug_key" in str(exc.orig):
            raise AppError(409, "slug_taken", "An event with this slug already exists") from exc
        raise
    return event


@router.get("/events", response_model=EventPage)
async def list_events(
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> Response:
    key = cache.event_list_key(limit, cursor)
    if (cached := await cache.cache_get(key)) is not None:
        return _cached_json(cached, hit=True)
    stmt = select(Event).where(Event.status == EventStatus.published)
    if cursor:
        starts_at, event_id = decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Event.starts_at > starts_at,
                and_(Event.starts_at == starts_at, Event.id > event_id),
            )
        )
    rows = (await session.scalars(stmt.order_by(Event.starts_at, Event.id).limit(limit + 1))).all()
    page = rows[:limit]
    next_cursor = encode_cursor(page[-1].starts_at, page[-1].id) if len(rows) > limit else None
    body = EventPage(
        items=[EventOut.model_validate(e) for e in page], next_cursor=next_cursor
    ).model_dump_json()
    await cache.cache_set(key, body)  # the list refreshes by TTL only, no invalidation
    return _cached_json(body, hit=False)


@router.get("/events/{event_id}", response_model=EventDetail)
async def get_event(
    event_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> Response:
    key = cache.event_key(event_id)
    if (cached := await cache.cache_get(key)) is not None:
        return _cached_json(cached, hit=True)
    event = await session.get(Event, event_id)
    if event is None or event.status == EventStatus.draft:
        raise AppError(404, "not_found", "Event not found")
    categories = (
        await session.scalars(
            select(Category).where(Category.event_id == event_id).order_by(Category.name)
        )
    ).all()
    body = EventDetail(
        **EventOut.model_validate(event).model_dump(),
        categories=[category_out(c) for c in categories],
    ).model_dump_json()
    # Only successful reads are cached (404s never are). seats_left may lag by up to the TTL;
    # registration itself always goes to the database, so this cannot cause overbooking.
    await cache.cache_set(key, body)
    return _cached_json(body, hit=False)


@router.patch("/events/{event_id}", response_model=EventOut)
async def patch_event(
    event_id: uuid.UUID,
    body: EventPatch,
    _: CurrentUser = Depends(require_organizer),
    session: AsyncSession = Depends(get_session),
) -> Event:
    async with session.begin():
        event = await session.get(Event, event_id, with_for_update=True)
        if event is None:
            raise AppError(404, "not_found", "Event not found")
        changes = body.model_dump(exclude_unset=True)
        new_status = changes.pop("status", None)
        for field, value in changes.items():
            if value is None and field in {"name", "starts_at", "ends_at", "reg_opens_at",
                                           "reg_closes_at"}:
                raise AppError(422, "validation_error", f"{field} cannot be null")
            setattr(event, field, value)
        if not (event.starts_at < event.ends_at):
            raise AppError(422, "validation_error", "starts_at must be before ends_at")
        if not (event.reg_opens_at < event.reg_closes_at):
            raise AppError(422, "validation_error", "reg_opens_at must be before reg_closes_at")
        if not (event.reg_closes_at <= event.ends_at):
            raise AppError(422, "validation_error", "reg_closes_at must be at or before ends_at")
        if new_status is not None and new_status != event.status:
            if _NEXT_STATUS.get(event.status) != new_status:
                raise AppError(
                    409,
                    "invalid_status_transition",
                    f"Cannot move event from {event.status.value} to {new_status.value}",
                )
            event.status = new_status
    await cache.cache_delete(cache.event_key(event_id))
    return event


@router.delete("/events/{event_id}", status_code=204)
async def delete_event(
    event_id: uuid.UUID,
    _: CurrentUser = Depends(require_organizer),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Delete an event, its categories and any forming teams, but only if nobody has registered.

    Registrations are people's history (and what check-in and the CSV rely on), so an event that
    has any is closed, never deleted. The categories are locked first, exactly as a registration
    locks its category, so a registration cannot slip in between the check and the delete.
    """
    try:
        async with session.begin():
            event = await session.get(Event, event_id, with_for_update=True)
            if event is None:
                raise AppError(404, "not_found", "Event not found")
            category_ids = (
                await session.scalars(
                    select(Category.id).where(Category.event_id == event_id).with_for_update()
                )
            ).all()
            registered = 0
            if category_ids:
                registered = (
                    await session.scalar(
                        select(func.count())
                        .select_from(Registration)
                        .where(Registration.category_id.in_(category_ids))
                    )
                ) or 0
            if registered:
                raise AppError(
                    409,
                    "event_has_registrations",
                    "This event has registrations, so it cannot be deleted. Close it instead.",
                )
            # Categories, teams and team members go with it (ON DELETE CASCADE).
            await session.execute(delete(Event).where(Event.id == event_id))
    except IntegrityError as exc:  # a registration that committed in the instant after the check
        raise AppError(
            409,
            "event_has_registrations",
            "This event has registrations, so it cannot be deleted. Close it instead.",
        ) from exc
    await cache.cache_delete(cache.event_key(event_id))
    return Response(status_code=204)


@router.post("/events/{event_id}/categories", response_model=CategoryOut, status_code=201)
async def create_category(
    event_id: uuid.UUID,
    body: CategoryCreate,
    _: CurrentUser = Depends(require_organizer),
    session: AsyncSession = Depends(get_session),
) -> CategoryOut:
    category = Category(event_id=event_id, **body.model_dump())
    try:
        async with session.begin():
            if await session.get(Event, event_id) is None:
                raise AppError(404, "not_found", "Event not found")
            session.add(category)
            await session.flush()
            await session.refresh(category)
    except IntegrityError as exc:
        if "categories_event_id_name_key" in str(exc.orig):
            raise AppError(409, "category_name_taken", "Category name already used") from exc
        raise
    await cache.cache_delete(cache.event_key(event_id))
    return category_out(category)
