import uuid

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import CurrentUser, get_current_user, require_organizer
from app.errors import AppError
from app.routers.common import stored_json_response
from app.routers.events import category_out
from app.schemas import CategoryOut, CategoryPatch, RegistrationOut
from app.services import idempotency, registration_service

router = APIRouter(tags=["categories"])


@router.patch("/categories/{category_id}", response_model=CategoryOut)
async def patch_category(
    category_id: uuid.UUID,
    body: CategoryPatch,
    _: CurrentUser = Depends(require_organizer),
    session: AsyncSession = Depends(get_session),
) -> CategoryOut:
    try:
        async with session.begin():
            # Same lock as seat claims and cancellations (CLAUDE.md rule).
            category = await registration_service.lock_category(session, category_id)
            changes = body.model_dump(exclude_unset=True)
            for field in ("name", "sport", "capacity", "waitlist_enabled"):
                if field in changes and changes[field] is None:
                    raise AppError(422, "validation_error", f"{field} cannot be null")
            new_capacity = changes.get("capacity")
            if new_capacity is not None and new_capacity < category.confirmed_count:
                raise AppError(
                    409,
                    "capacity_below_confirmed",
                    "Capacity cannot be lower than the confirmed count",
                )
            for field, value in changes.items():
                setattr(category, field, value)
            if new_capacity is not None:
                # Fill any new seats from the waitlist while still holding the lock.
                await session.flush()
                promoted = await registration_service.promote_waitlist(
                    session, category_id, new_capacity - category.confirmed_count
                )
                category.confirmed_count += promoted
            await session.flush()
    except IntegrityError as exc:
        if "categories_event_id_name_key" in str(exc.orig):
            raise AppError(409, "category_name_taken", "Category name already used") from exc
        raise
    return category_out(category)


@router.post(
    "/categories/{category_id}/registrations", response_model=RegistrationOut, status_code=201
)
async def register(
    category_id: uuid.UUID,
    request: Request,
    idempotency_key: str | None = Header(default=None),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    if not idempotency_key:
        raise AppError(400, "missing_idempotency_key", "Idempotency-Key header is required")
    method, path = request.method, request.url.path
    status, body = await registration_service.register_individual(
        session,
        user,
        category_id,
        idempotency_key=idempotency_key,
        method=method,
        path=path,
        request_hash=idempotency.hash_request(method, path, await request.body()),
    )
    return stored_json_response(status, body)
