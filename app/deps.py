import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Header
from sqlalchemy import text

from app.config import get_settings
from app.db import SessionLocal
from app.errors import AppError
from app.models import UserRole


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    email: str
    role: UserRole


async def _get_or_create_dev_user(email: str, role: UserRole) -> CurrentUser:
    """Find the user for this email, creating it on first sight (dev auth only)."""
    auth_id = f"dev:{email.lower()}"
    name = email.split("@", 1)[0]
    # Own short-lived session so the request's session starts with a clean transaction.
    async with SessionLocal() as session, session.begin():
        await session.execute(
            text(
                "INSERT INTO users (auth_id, email, name, role) "
                "VALUES (:auth_id, :email, :name, :role) ON CONFLICT DO NOTHING"
            ),
            {"auth_id": auth_id, "email": email, "name": name, "role": role.value},
        )
        row = (
            await session.execute(
                text("SELECT id, email, role FROM users WHERE auth_id = :auth_id"),
                {"auth_id": auth_id},
            )
        ).one()
    return CurrentUser(id=row.id, email=str(row.email), role=UserRole(row.role))


async def get_current_user(
    x_dev_user: str | None = Header(default=None),
    x_dev_role: str | None = Header(default=None),
) -> CurrentUser:
    settings = get_settings()
    if settings.auth_mode != "dev":
        raise AppError(501, "auth_not_implemented", "Clerk auth is not implemented yet")
    if not x_dev_user or "@" not in x_dev_user:
        raise AppError(401, "unauthenticated", "Missing or invalid X-Dev-User header")
    try:
        role = UserRole(x_dev_role) if x_dev_role else UserRole.participant
    except ValueError:
        raise AppError(400, "invalid_dev_role", f"Unknown role: {x_dev_role}") from None
    return await _get_or_create_dev_user(x_dev_user.strip(), role)


def require_role(*roles: UserRole) -> Callable[..., Awaitable[CurrentUser]]:
    from fastapi import Depends

    async def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise AppError(403, "forbidden", "You do not have permission to do this")
        return user

    return checker


ORGANIZER_ROLES = (UserRole.organizer, UserRole.admin)
require_organizer = require_role(*ORGANIZER_ROLES)
