"""Clerk session-token verification (SPEC decision 4): RS256 JWT checked against Clerk's JWKS."""

import asyncio
import logging
from functools import lru_cache
from typing import Any, Protocol

import jwt
from jwt import PyJWKClient
from jwt.exceptions import (
    ExpiredSignatureError,
    InvalidTokenError,
    PyJWKClientConnectionError,
    PyJWKClientError,
)

from app.config import get_settings
from app.errors import AppError

log = logging.getLogger("auth")


class SigningKeyResolver(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> Any: ...


class ClerkVerifier:
    def __init__(self, issuer: str, keys: SigningKeyResolver) -> None:
        self._issuer = issuer
        self._keys = keys

    async def verify(self, token: str) -> dict[str, Any]:
        """Return the verified claims, or raise AppError (401, or 503 if Clerk is unreachable)."""
        try:
            # PyJWKClient does blocking HTTP (and caches keys), so keep it off the event loop.
            signing_key = await asyncio.to_thread(self._keys.get_signing_key_from_jwt, token)
            claims: dict[str, Any] = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],  # never trust the token's own "alg" header
                issuer=self._issuer,
                options={"require": ["exp", "iat", "sub", "iss"], "verify_aud": False},
                leeway=10,  # tolerate small clock drift between Clerk and us
            )
        except ExpiredSignatureError:
            raise AppError(401, "token_expired", "The session token has expired") from None
        except PyJWKClientConnectionError:
            log.exception("could not reach Clerk's JWKS endpoint")
            raise AppError(503, "auth_unavailable", "Cannot verify sign-in right now") from None
        except (PyJWKClientError, InvalidTokenError):
            raise AppError(401, "invalid_auth_token", "The session token is not valid") from None
        return claims


@lru_cache
def get_verifier() -> ClerkVerifier:
    settings = get_settings()
    keys = PyJWKClient(settings.clerk_jwks_url, cache_keys=True, lifespan=3600)
    return ClerkVerifier(settings.clerk_issuer, keys)


def identity_from_claims(claims: dict[str, Any]) -> tuple[str, str, str]:
    """(auth_id, email, name) from verified claims.

    Clerk's default session token has no email or name: they must be added as custom claims
    in the session token template (`email` and, optionally, `name`).
    """
    email = str(claims.get("email") or "").strip()
    if "@" not in email:
        raise AppError(
            401,
            "missing_email_claim",
            "The session token has no email claim; add one to the Clerk session token template",
        )
    name = str(claims.get("name") or "").strip() or email.split("@", 1)[0]
    return f"clerk:{claims['sub']}", email, name
