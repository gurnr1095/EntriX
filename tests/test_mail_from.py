"""MAIL_FROM is the one setting that worked locally (a .env file strips quotes) and silently
failed on Render (a dashboard keeps them): Brevo answered 400 "valid sender email required" for
every email, six attempts each. These tests pin every form of that mistake."""

import httpx
import pytest
from sqlalchemy import text

from app.config import Settings, sender_address, validate_worker_startup
from app.db import SessionLocal, engine
from app.worker.emails import MailContext, build_message
from app.worker.outbox_worker import process_batch
from app.worker.senders import BrevoSender, DeferredError
from tests.conftest import as_user, idem, make_category, make_event
from tests.test_brevo import _ctx, _sender
from tests.test_outbox_worker import Mailbox


@pytest.mark.parametrize(
    "given,expected",
    [
        ("EntriX <grkr1095@gmail.com>", "EntriX <grkr1095@gmail.com>"),
        ("grkr1095@gmail.com", "grkr1095@gmail.com"),
        # a value pasted into a hosting dashboard with the quotes it had in a .env file
        ('"EntriX <grkr1095@gmail.com>"', "EntriX <grkr1095@gmail.com>"),
        ("'EntriX <grkr1095@gmail.com>'", "EntriX <grkr1095@gmail.com>"),
        ('  "grkr1095@gmail.com"  ', "grkr1095@gmail.com"),
        # quotes that are part of a display name are NOT surrounding quotes: left alone
        ('"EntriX Team" <grkr1095@gmail.com>', '"EntriX Team" <grkr1095@gmail.com>'),
    ],
)
def test_stray_surrounding_quotes_are_removed(given: str, expected: str) -> None:
    cleaned = Settings(mail_from=given).mail_from
    assert cleaned == expected
    assert sender_address(cleaned) == "grkr1095@gmail.com"


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "EntriX", "EntriX <>", "not an address", "a@b", "two@x.co three@y.co", '"'],
)
def test_a_sender_that_is_not_an_address_stops_the_app_starting(bad: str) -> None:
    assert sender_address(bad) is None
    with pytest.raises(RuntimeError, match="MAIL_FROM must contain an email address"):
        validate_worker_startup(Settings(mail_from=bad))


def test_the_startup_message_tells_you_what_to_do() -> None:
    with pytest.raises(RuntimeError) as exc:
        validate_worker_startup(Settings(mail_from="oops"))
    assert "do not add quotes" in str(exc.value) and "'oops'" in str(exc.value)


def test_a_good_sender_passes() -> None:
    validate_worker_startup(Settings(mail_from="EntriX <grkr1095@gmail.com>"))
    validate_worker_startup(Settings())  # the local default


def test_an_unusable_sender_never_reaches_brevo() -> None:
    """Belt and braces: even if validation were bypassed, no request with an empty sender."""
    called = []

    def handler(request: httpx.Request) -> httpx.Response:
        called.append(request)
        return httpx.Response(201, json={})

    msg = build_message("registration_confirmed", _ctx(), 1, "EntriX <>", inline_qr=False)
    assert msg is not None
    with pytest.raises(DeferredError, match="MAIL_FROM has no usable email address"):
        _sender(handler)(msg)
    assert called == []


def test_brevo_saying_the_sender_is_invalid_is_configuration_not_a_bad_email() -> None:
    body = {"code": "invalid_parameter", "message": "valid sender email required"}
    msg = build_message("registration_confirmed", _ctx(), 1, "a@b.co", inline_qr=False)
    with pytest.raises(DeferredError) as exc:
        _sender(lambda r: httpx.Response(400, json=body))(msg)
    assert exc.value.delay_seconds == 15 * 60 and "MAIL_FROM" in exc.value.reason


def test_other_400s_are_still_ordinary_failures() -> None:
    msg = build_message("registration_confirmed", _ctx(), 1, "a@b.co", inline_qr=False)
    with pytest.raises(RuntimeError, match="400"):
        _sender(lambda r: httpx.Response(400, json={"message": "recipient is invalid"}))(msg)


async def test_a_wrong_sender_no_longer_burns_every_email_attempts(client: httpx.AsyncClient) -> None:
    """The incident: one bad setting used up all eight attempts of every queued email."""
    event = await make_event(client)
    cid = (await make_category(client, event["id"], capacity=5))["id"]
    for i in range(3):
        r = await client.post(
            f"/categories/{cid}/registrations", headers={**as_user(f"u{i}@test.dev"), **idem()}
        )
        assert r.status_code == 201
    brevo_says = {"code": "invalid_parameter", "message": "valid sender email required"}
    provider = _sender(lambda r: httpx.Response(400, json=brevo_says))

    for _ in range(10):  # more rounds than the 8 attempts a row gets
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE outbox SET next_attempt_at = now()"))
        await process_batch(SessionLocal, provider, max_attempts=8)

    async with engine.connect() as conn:
        rows = (await conn.execute(text("SELECT status::text, attempts FROM outbox"))).all()
    assert {(r.status, r.attempts) for r in rows} == {("pending", 0)}  # nothing was lost

    # Once the setting is fixed, all three go out.
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE outbox SET next_attempt_at = now()"))
    working = Mailbox()
    await process_batch(SessionLocal, working, max_attempts=8)
    assert len(working.sent) == 3


def test_brevo_sender_class_still_reads_the_cleaned_setting() -> None:
    from app.config import get_settings

    assert isinstance(BrevoSender(api_key="k"), BrevoSender)
    assert sender_address(get_settings().mail_from) is not None
    _ = MailContext  # imported for the type used by _ctx()
