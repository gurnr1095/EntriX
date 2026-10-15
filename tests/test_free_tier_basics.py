import httpx
import pytest

from app.config import Settings, normalise_database_url, validate_worker_startup
from app.worker import outbox_worker
from app.worker.senders import BrevoSender
from tests.conftest import as_user
from tests.test_cache import count_queries


@pytest.mark.parametrize(
    "given,expected",
    [
        ("postgres://u:p@h/db", "postgresql+asyncpg://u:p@h/db"),
        ("postgresql://u:p@h:5432/db", "postgresql+asyncpg://u:p@h:5432/db"),
        # Neon's copy-paste URL: asyncpg wants `ssl`, and rejects `channel_binding` outright.
        (
            "postgresql://u:p@ep-cool-123.neon.tech/neondb?sslmode=require&channel_binding=require",
            "postgresql+asyncpg://u:p@ep-cool-123.neon.tech/neondb?ssl=require",
        ),
        (
            "postgres://u:p@h/db?sslmode=verify-full&application_name=entrix",
            "postgresql+asyncpg://u:p@h/db?ssl=verify-full&application_name=entrix",
        ),
        # already in the right shape: untouched
        ("postgresql+asyncpg://u:p@h/db?ssl=require", "postgresql+asyncpg://u:p@h/db?ssl=require"),
        # a password containing an escaped '@' survives
        ("postgres://u:p%40ss@h/db?sslmode=require", "postgresql+asyncpg://u:p%40ss@h/db?ssl=require"),
    ],
)
def test_database_urls_from_hosting_providers_are_made_asyncpg_friendly(
    given: str, expected: str
) -> None:
    assert normalise_database_url(given) == expected
    assert Settings(database_url=given).database_url == expected  # applied to the setting


def test_non_postgres_urls_are_left_alone() -> None:
    assert normalise_database_url("sqlite:///x.db?sslmode=require") == "sqlite:///x.db?sslmode=require"


async def test_livez_is_up_without_touching_the_database(client: httpx.AsyncClient) -> None:
    with count_queries() as queries:
        r = await client.get("/livez")
    assert r.status_code == 200 and r.json() == {"status": "alive"}
    assert queries == []  # a keep-alive ping must never wake a sleeping database

    with count_queries() as queries:
        r = await client.get("/healthz")  # the readiness check still proves the database works
    assert r.status_code == 200 and queries != []


def test_email_backend_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    settings = get_settings()
    assert outbox_worker.get_sender() is outbox_worker.smtp_send  # the default, as before

    monkeypatch.setattr(settings, "email_backend", "brevo")
    monkeypatch.setattr(settings, "brevo_api_key", "k")
    assert isinstance(outbox_worker.get_sender(), BrevoSender)


def test_brevo_backend_needs_an_api_key() -> None:
    with pytest.raises(RuntimeError, match="BREVO_API_KEY"):
        validate_worker_startup(Settings(email_backend="brevo"))
    validate_worker_startup(Settings(email_backend="brevo", brevo_api_key="k"))
    validate_worker_startup(Settings())  # smtp needs nothing


async def test_livez_needs_no_login(client: httpx.AsyncClient) -> None:
    assert (await client.get("/livez")).status_code == 200
    assert (await client.get("/me", headers=as_user("x@test.dev"))).status_code == 200
