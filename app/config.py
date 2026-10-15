import re
from email.utils import formataddr, parseaddr
from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_EMAIL = re.compile(r"[^@\s<>\"',;]+@[^@\s<>\"',;]+\.[^@\s<>\"',;]+")


def sender_address(mail_from: str) -> str | None:
    """The bare email address inside MAIL_FROM ("Name <a@b.co>" or "a@b.co"), or None if it
    does not contain a usable one (empty, stray quotes, a missing <...>)."""
    address = parseaddr(mail_from)[1]
    return address if _EMAIL.fullmatch(address) else None


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
    # The name recipients see ("EntriX"). Kept separate so MAIL_FROM can be a plain address:
    # `Name <address>` is easy to mistype in a hosting dashboard.
    mail_from_name: str = ""
    outbox_poll_seconds: float = 2
    # Longest the worker sleeps when nothing is due. Small for a dedicated worker; a free-tier
    # deployment sets it high so an idle database can suspend (a new registration wakes the
    # worker immediately regardless, see services/outbox.py).
    outbox_idle_poll_seconds: float = 2
    outbox_max_attempts: int = 8
    # Run the outbox worker inside the API process (free hosting has no background workers).
    run_worker_in_api: bool = False
    # How emails leave the system. "smtp" for MailHog or a normal SMTP server; "brevo" sends
    # through Brevo's HTTPS API, for hosts that block outbound SMTP ports.
    email_backend: Literal["smtp", "brevo"] = "smtp"
    brevo_api_key: str = ""

    @field_validator("database_url", "test_database_url")
    @classmethod
    def _async_driver(cls, value: str) -> str:
        return normalise_database_url(value)

    @field_validator("mail_from", "mail_from_name")
    @classmethod
    def _unquote_mail_from(cls, value: str) -> str:
        """A value pasted into a hosting dashboard keeps the quotes it had in a .env file
        (`MAIL_FROM="EntriX <a@b.co>"`); a .env parser strips them, a dashboard does not."""
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1].strip()
        return value

    def sender_header(self) -> str:
        """The value for the From header: `Name <address>`, or just the address.

        MAIL_FROM_NAME wins over a name written inside MAIL_FROM.
        """
        address = sender_address(self.mail_from)
        if address is None:
            return self.mail_from  # validate_worker_startup reports this clearly
        name = self.mail_from_name or parseaddr(self.mail_from)[0]
        return formataddr((name, address)) if name else address


def normalise_database_url(url: str) -> str:
    """Turn a hosting provider's Postgres URL into one SQLAlchemy + asyncpg understand.

    Providers (Render, Neon, ...) hand out `postgres://` or `postgresql://` URLs, and Neon's
    carry libpq options asyncpg rejects: `sslmode=require` must be spelled `ssl=require`, and
    `channel_binding` is not supported at all.
    """
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+asyncpg://" + url[len(prefix) :]
    if not url.startswith("postgresql+asyncpg://"):
        return url
    parts = urlsplit(url)
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key == "channel_binding":
            continue
        query.append(("ssl" if key == "sslmode" else key, value))
    return urlunsplit(parts._replace(query=urlencode(query)))


@lru_cache
def get_settings() -> Settings:
    return Settings()


def validate_worker_startup(settings: Settings) -> None:
    """Checks every process needs (the worker signs QR codes too)."""
    if settings.env == "prod" and settings.qr_secret in {"", "change-me"}:
        raise RuntimeError("QR_SECRET must be set to a long random value when ENV=prod")
    if settings.email_backend == "brevo" and not settings.brevo_api_key:
        raise RuntimeError("EMAIL_BACKEND=brevo needs BREVO_API_KEY")
    if sender_address(settings.mail_from) is None:
        raise RuntimeError(
            "MAIL_FROM must contain an email address: use just the address you verified with "
            "your email provider, e.g.  you@example.com  (put the display name in "
            f"MAIL_FROM_NAME). Got {settings.mail_from!r}. In a hosting dashboard, do not add "
            "quotes, and a  Name <address>  form needs its angle brackets."
        )


def validate_startup(settings: Settings) -> None:
    """Refuse to boot the API in unsafe configurations."""
    validate_worker_startup(settings)
    if settings.env == "prod" and settings.auth_mode == "dev":
        raise RuntimeError("AUTH_MODE=dev is not allowed when ENV=prod")
    if settings.auth_mode == "clerk" and not (settings.clerk_jwks_url and settings.clerk_issuer):
        raise RuntimeError("AUTH_MODE=clerk needs CLERK_JWKS_URL and CLERK_ISSUER")
