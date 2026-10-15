from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["dev", "prod"] = "dev"
    auth_mode: Literal["dev", "clerk"] = "dev"
    clerk_jwks_url: str = ""
    clerk_issuer: str = ""
    database_url: str = "postgresql+asyncpg://sportreg:sportreg@localhost:5433/sportreg"
    test_database_url: str = (
        "postgresql+asyncpg://sportreg:sportreg@localhost:5433/sportreg_test"
    )
    # Per-process connection pool: total connections = workers x (pool_size + max_overflow),
    # which must stay under Postgres's max_connections (100 by default).
    db_pool_size: int = 20
    db_max_overflow: int = 20

    # Empty REDIS_URL means in-memory rate limiting and caching (tests, single process).
    redis_url: str = ""
    rate_limit_enabled: bool = True
    rate_limit_user_per_min: int = 10  # registration endpoints, per user
    rate_limit_ip_per_min: int = 60  # registration endpoints, per client IP
    rate_limit_checkin_per_min: int = 120  # check-in, per volunteer
    # How many trusted reverse proxies sit in front of the app. 0 = use the socket address;
    # N = take the Nth entry from the right of X-Forwarded-For (the left side is client-forged).
    trusted_proxy_hops: int = 0
    cache_enabled: bool = True
    cache_ttl_seconds: int = 3

    qr_secret: str = "change-me"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = False
    mail_from: str = "no-reply@sportreg.local"
    outbox_poll_seconds: float = 2
    outbox_max_attempts: int = 8

    @field_validator("database_url", "test_database_url")
    @classmethod
    def _async_driver(cls, value: str) -> str:
        """Hosting platforms hand out postgres:// or postgresql:// URLs; we need asyncpg."""
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+asyncpg://" + value[len(prefix) :]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


def validate_worker_startup(settings: Settings) -> None:
    """Checks every process needs (the worker signs QR codes too)."""
    if settings.env == "prod" and settings.qr_secret in {"", "change-me"}:
        raise RuntimeError("QR_SECRET must be set to a long random value when ENV=prod")


def validate_startup(settings: Settings) -> None:
    """Refuse to boot the API in unsafe configurations."""
    validate_worker_startup(settings)
    if settings.env == "prod" and settings.auth_mode == "dev":
        raise RuntimeError("AUTH_MODE=dev is not allowed when ENV=prod")
    if settings.auth_mode == "clerk" and not (settings.clerk_jwks_url and settings.clerk_issuer):
        raise RuntimeError("AUTH_MODE=clerk needs CLERK_JWKS_URL and CLERK_ISSUER")
