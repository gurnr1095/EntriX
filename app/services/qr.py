import base64
import hashlib
import hmac
import uuid

from app.config import get_settings
from app.errors import AppError


def _signature(registration_id: uuid.UUID, category_id: uuid.UUID) -> str:
    message = f"reg:{registration_id}:{category_id}".encode()
    digest = hmac.new(get_settings().qr_secret.encode(), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def sign(registration_id: uuid.UUID, category_id: uuid.UUID) -> str:
    """Token format from SPEC 4.5: `<registration_id>.<b64url(HMAC)>`. Carries no PII."""
    return f"{registration_id}.{_signature(registration_id, category_id)}"


def parse(token: str) -> tuple[uuid.UUID, str]:
    """Split a token into (registration_id, signature). Raises invalid_token if malformed."""
    reg_part, sep, signature = token.partition(".")
    if not sep or not signature:
        raise AppError(400, "invalid_token", "Malformed token")
    try:
        return uuid.UUID(reg_part), signature
    except ValueError:
        raise AppError(400, "invalid_token", "Malformed token") from None


def verify(registration_id: uuid.UUID, category_id: uuid.UUID, signature: str) -> None:
    """Constant-time signature check; raises invalid_token on any mismatch."""
    expected = _signature(registration_id, category_id)
    if not hmac.compare_digest(expected.encode(), signature.encode()):
        raise AppError(400, "invalid_token", "Invalid token")
