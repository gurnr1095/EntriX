"""The deployed-API smoke script, run against the real app in-process (dev auth, real Postgres),
so the script is proven before it ever touches production."""

import httpx
from sqlalchemy import text

from app.db import engine
from app.main import app
from scripts.smoke_test_deployed import amain, run_smoke
from tests.conftest import as_user


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=60)


async def test_every_step_passes_against_the_real_app() -> None:
    lines: list[str] = []
    async with _client() as client:
        passed = await run_smoke(client, as_user("smoke@test.dev", "admin"), lines.append)

    assert passed, "\n".join(lines)
    steps = [line for line in lines if line.startswith("[")]
    assert len(steps) >= 20 and all(line.startswith("[  OK]") for line in steps)
    assert any("idempotency" in line for line in steps)
    assert any("forged" in line for line in steps)
    assert "All" in lines[-1] and "inbox" in lines[-1]

    async with engine.connect() as conn:  # it really did the work, and left the event closed
        assert await conn.scalar(text("SELECT status::text FROM events")) == "closed"
        assert await conn.scalar(text("SELECT status::text FROM registrations")) == "checked_in"
        assert await conn.scalar(text("SELECT count(*) FROM outbox WHERE event_type = 'registration_confirmed'")) == 1


async def test_a_participant_is_stopped_with_the_fix_spelled_out() -> None:
    lines: list[str] = []
    async with _client() as client:
        passed = await run_smoke(client, as_user("just.a.student@test.dev"), lines.append)

    assert not passed
    joined = "\n".join(lines)
    assert "UPDATE users SET role" in joined and "Stopped at" in joined
    async with engine.connect() as conn:  # and it created nothing before stopping
        assert await conn.scalar(text("SELECT count(*) FROM events")) == 0


async def test_a_bad_credential_gets_a_useful_hint() -> None:
    lines: list[str] = []
    async with _client() as client:
        passed = await run_smoke(client, {}, lines.append)  # no login at all
    assert not passed
    assert "unauthenticated" in "\n".join(lines) and "ENTRIX_TOKEN" in "\n".join(lines)


async def test_without_a_url_or_token_it_prints_the_usage(capsys, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("ENTRIX_TOKEN", raising=False)
    assert await amain([]) == 2
    assert "smoke_test_deployed" in capsys.readouterr().out


async def test_a_missing_token_is_explained_specifically(capsys, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("ENTRIX_TOKEN", raising=False)
    assert await amain(["https://example.onrender.com"]) == 2
    out = capsys.readouterr().out
    assert "ENTRIX_TOKEN variable is empty" in out and "Remember the token" in out
    assert "No service URL" not in out  # it must not complain about what was given


async def test_a_missing_url_is_explained_specifically(capsys, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ENTRIX_TOKEN", "x" * 100)
    assert await amain([]) == 2
    out = capsys.readouterr().out
    assert "No service URL given" in out and "ENTRIX_TOKEN variable is empty" not in out
