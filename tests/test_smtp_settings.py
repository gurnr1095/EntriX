from email.message import EmailMessage
from typing import Any

import pytest

from app.config import get_settings
from app.worker import outbox_worker


class FakeSMTP:
    calls: list[tuple[str, Any]] = []

    def __init__(self, host: str, port: int, timeout: float) -> None:
        FakeSMTP.calls.append(("connect", (host, port)))

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *_: Any) -> None:
        FakeSMTP.calls.append(("quit", None))

    def starttls(self, context: Any = None) -> None:
        FakeSMTP.calls.append(("starttls", context is not None))

    def login(self, user: str, password: str) -> None:
        FakeSMTP.calls.append(("login", (user, password)))

    def send_message(self, msg: EmailMessage) -> None:
        FakeSMTP.calls.append(("send", msg["To"]))


@pytest.fixture(autouse=True)
def _fake_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeSMTP.calls = []
    monkeypatch.setattr(outbox_worker.smtplib, "SMTP", FakeSMTP)


def _message() -> EmailMessage:
    msg = EmailMessage()
    msg["To"] = "x@test.dev"
    return msg


def test_plain_smtp_for_mailhog(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defaults (local MailHog): no TLS and no login."""
    outbox_worker.smtp_send(_message())
    assert [c[0] for c in FakeSMTP.calls] == ["connect", "send", "quit"]


def test_real_provider_uses_starttls_then_login(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_starttls", True)
    monkeypatch.setattr(settings, "smtp_user", "apikey")
    monkeypatch.setattr(settings, "smtp_password", "s3cret")
    outbox_worker.smtp_send(_message())
    # TLS must be on before credentials are sent.
    assert [c[0] for c in FakeSMTP.calls] == ["connect", "starttls", "login", "send", "quit"]
    assert ("login", ("apikey", "s3cret")) in FakeSMTP.calls
    assert ("starttls", True) in FakeSMTP.calls
