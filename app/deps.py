import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Depends, Header, Request
from sqlalchemy import text

from app import auth_clerk
from app.config import get_settings
from app.db import SessionLocal
from app.errors import AppError
from app.models import UserRole
from app.services import rate_limit


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    email: str
    role: UserRole


async def _get_or_create_user(auth_id: str, email: str, name: str, role: UserRole) -> CurrentUser:
    """Find the user for this identity, creating it on first sight.

    `role` only applies to a brand-new row; an existing user keeps the role stored in the
    database (that is what stops a client choosing its own role).
    """
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
        ).first()
    if row is None:
        # The insert was skipped by the email's unique constraint: another identity owns it.
        raise AppError(409, "account_conflict", "An account with this email already exists")
    return CurrentUser(id=row.id, email=str(row.email), role=UserRole(row.role))


async def _dev_user(x_dev_user: str | None, x_dev_role: str | None) -> CurrentUser:
    if not x_dev_user or "@" not in x_dev_user:
        raise AppError(401, "unauthenticated", "Missing or invalid X-Dev-User header")
    try:
        role = UserRole(x_dev_role) if x_dev_role else UserRole.participant
    except ValueError:
        raise AppError(400, "invalid_dev_role", f"Unknown role: {x_dev_role}") from None
    email = x_dev_user.strip()
    return await _get_or_create_user(
        f"dev:{email.lower()}", email, email.split("@", 1)[0], role
    )


async def _clerk_user(authorization: str | None) -> CurrentUser:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AppError(401, "unauthenticated", "Missing bearer token")
    claims = await auth_clerk.get_verifier().verify(token.strip())
    auth_id, email, name = auth_clerk.identity_from_claims(claims)
    # Roles are never read from the token: new users are participants, and an admin promotes
    # people in the database.
    return await _get_or_create_user(auth_id, email, name, UserRole.participant)


async def get_current_user(
    x_dev_user: str | None = Header(default=None),
    x_dev_role: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    if get_settings().auth_mode == "clerk":
        # The dev headers are not even looked at in clerk mode: nobody can impersonate.
        return await _clerk_user(authorization)
    return await _dev_user(x_dev_user, x_dev_role)


def require_role(*roles: UserRole) -> Callable[..., Awaitable[CurrentUser]]:
    async def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise AppError(403, "forbidden", "You do not have permission to do this")
        return user

    return checker


ORGANIZER_ROLES = (UserRole.organizer, UserRole.admin)
require_organizer = require_role(*ORGANIZER_ROLES)


async def registration_rate_limit(
    request: Request, user: CurrentUser = Depends(get_current_user)
) -> None:
    """SPEC 5: registration POSTs are limited per user and per client IP."""
    settings = get_settings()
    await rate_limit.enforce(
        request,
        scope="register",
        user_id=user.id,
        user_limit=settings.rate_limit_user_per_min,
        ip_limit=settings.rate_limit_ip_per_min,
    )
