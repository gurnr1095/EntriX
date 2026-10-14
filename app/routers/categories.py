import json
import uuid

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import CurrentUser, get_current_user, require_organizer
from app.errors import AppError
from app.models import Category
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
            category = await session.scalar(
                select(Category)
                .where(Category.id == category_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if category is None:
                raise AppError(404, "not_found", "Category not found")
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
    # jsonb does not preserve key order, so serialize with sorted keys: a fresh response
    # and a replay are then byte-identical.
    return Response(
        content=json.dumps(body, sort_keys=True, separators=(",", ":")),
        status_code=status,
        media_type="application/json",
    )
