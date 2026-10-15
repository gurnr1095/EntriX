from email.message import EmailMessage

from app.config import Settings
from app.worker.senders import DeferredError
from scripts.send_test_email import main, send_test_emails
from tests.test_outbox_worker import Mailbox


def test_sends_one_marked_test_email_per_recipient() -> None:
    box = Mailbox()
    results = send_test_emails(["a@x.co", "b@y.co"], box, Settings(mail_from="events@example.com"))

    assert results == [("a@x.co", None), ("b@y.co", None)]
    assert [m["To"] for m in box.sent] == ["a@x.co", "b@y.co"]
    assert all(m["Subject"].startswith("[EntriX test] ") for m in box.sent)
    assert all(m["From"] == "events@example.com" for m in box.sent)
    assert all(any(p.get_content_type() == "image/png" for p in m.walk()) for m in box.sent)


def test_one_failure_does_not_stop_the_rest() -> None:
    class Picky:
        inline_images = False

        def __call__(self, msg: EmailMessage) -> None:
            if msg["To"] == "bad@x.co":
                raise ConnectionError("no route")
            if msg["To"] == "slow@x.co":
                raise DeferredError(60, "daily quota used up")

    results = dict(send_test_emails(["bad@x.co", "slow@x.co", "ok@x.co"], Picky(), Settings()))
    assert "ConnectionError" in (results["bad@x.co"] or "")
    assert "not now" in (results["slow@x.co"] or "")
    assert results["ok@x.co"] is None


def test_the_attachment_layout_is_used_for_senders_without_inline_images() -> None:
    class NoInline(Mailbox):
        inline_images = False

    box = NoInline()
    send_test_emails(["a@x.co"], box, Settings())
    assert box.sent[0].get_content_type() == "multipart/mixed"


def test_no_recipients_prints_the_usage(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main([]) == 2
    assert "send_test_email" in capsys.readouterr().out


# ---- main(): the guard rails around real sending ----


def _patch(monkeypatch, backend: str = "smtp", host: str = "localhost"):  # type: ignore[no-untyped-def]
    from app.config import get_settings
    from scripts import send_test_email as script

    box = Mailbox()
    settings = get_settings()
    monkeypatch.setattr(settings, "email_backend", backend)
    monkeypatch.setattr(settings, "smtp_host", host)
    monkeypatch.setattr(settings, "brevo_api_key", "k")
    monkeypatch.setattr(script, "get_sender", lambda: box)
    return box


def test_example_addresses_from_the_docs_are_refused(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    box = _patch(monkeypatch, backend="brevo")
    assert main(["you@gmail.com", "another@outlook.com", "real.person@gmail.com"]) == 2
    assert "example addresses" in capsys.readouterr().out
    assert box.sent == []  # not even the real one: fix the command first


def test_the_local_mailhog_default_is_refused_with_instructions(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    box = _patch(monkeypatch)  # smtp to localhost, as with no .env file
    assert main(["my.own@gmail.com"]) == 3
    out = capsys.readouterr().out
    assert "EMAIL_BACKEND=brevo" in out and ".env" in out and "BREVO_API_KEY" in out
    assert box.sent == []


def test_local_sending_is_possible_when_asked_for(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    box = _patch(monkeypatch)
    assert main(["my.own@gmail.com", "--allow-local"]) == 0
    assert len(box.sent) == 1
    out = capsys.readouterr().out
    assert "MailHog only" in out and "spam folder" not in out  # no misleading Brevo advice


def test_brevo_runs_send_and_show_the_inbox_and_spam_advice(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    box = _patch(monkeypatch, backend="brevo")
    assert main(["my.own@gmail.com", "my.other@outlook.com"]) == 0
    assert len(box.sent) == 2
    assert "spam folder" in capsys.readouterr().out
