import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError
from app.models import IdempotencyKey


@dataclass(frozen=True)
class Replay:
    status: int
    body: dict[str, Any]


def hash_request(method: str, path: str, raw_body: bytes) -> str:
    """Stable fingerprint of a request: method, path and canonical JSON body."""
    try:
        parsed = json.loads(raw_body) if raw_body.strip() else {}
    except ValueError:
        raise AppError(422, "validation_error", "Request body is not valid JSON") from None
    canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{method}\n{path}\n{canonical}".encode()).hexdigest()


async def claim(
    session: AsyncSession,
    user_id: uuid.UUID,
    key: str,
    method: str,
    path: str,
    request_hash: str,
) -> Replay | None:
    """Insert the key row inside the caller's transaction (SPEC 4.1 step 2).

    Returns None when this request owns the key and must do the work. A concurrent
    duplicate blocks on the unique index until the first transaction finishes: if that
    one committed we replay its stored response, if it rolled back we get to insert.
    """
    inserted = await session.scalar(
        text(
            "INSERT INTO idempotency_keys (user_id, key, method, path, request_hash) "
            "VALUES (:user_id, :key, :method, :path, :hash) "
            "ON CONFLICT DO NOTHING RETURNING key"
        ),
        {"user_id": user_id, "key": key, "method": method, "path": path, "hash": request_hash},
    )
    if inserted is not None:
        return None

    row = await session.scalar(
        select(IdempotencyKey)
        .where(IdempotencyKey.user_id == user_id, IdempotencyKey.key == key)
        .execution_options(populate_existing=True)
    )
    assert row is not None
    if row.request_hash != request_hash or row.method != method or row.path != path:
        raise AppError(
            422,
            "idempotency_key_reuse",
            "This Idempotency-Key was already used for a different request",
        )
    if row.response_status is None or row.response_body is None:
        # Only reachable if a row was committed without its response; never expected.
        raise AppError(409, "idempotency_in_progress", "A request with this key is in progress")
    return Replay(row.response_status, row.response_body)


async def store_response(
    session: AsyncSession, user_id: uuid.UUID, key: str, status: int, body: dict[str, Any]
) -> None:
    await session.execute(
        update(IdempotencyKey)
        .where(IdempotencyKey.user_id == user_id, IdempotencyKey.key == key)
        .values(response_status=status, response_body=body)
    )
