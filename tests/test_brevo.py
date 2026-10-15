import base64
import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.db import SessionLocal, engine
from app.models import RegistrationStatus
from app.worker.emails import MailContext, build_message
from app.worker.outbox_worker import process_batch
from app.worker.senders import BrevoSender as Brevo
from app.worker.senders import DeferredError
from tests.conftest import as_user, idem, make_category, make_event
from tests.test_outbox_worker import Mailbox

TOKEN = "11111111-2222-3333-4444-555555555555.abcDEF_-123"


def _ctx() -> MailContext:
    return MailContext(
        registration_id="reg-1",
        status=RegistrationStatus.confirmed,
        to_email="student@college.edu",
        name="Sam <b>Singh</b>",
        category_name="Table Tennis",
        event_name="Zeal",
        venue="Main Ground",
        starts_at=datetime(2026, 12, 1, 10, 0, tzinfo=UTC),
        token=TOKEN,
    )


def _sender(handler: Any, api_key: str = "secret-key") -> Brevo:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return Brevo(api_key=api_key, client=client, url="https://brevo.test/v3/smtp/email")


def _message(mail_from: str = "EntriX <events@example.com>") -> Any:
    msg = build_message("registration_confirmed", _ctx(), 42, mail_from, inline_qr=False)
    assert msg is not None
    return msg


# ------------------------------------------------------------ the email layout


def test_without_inline_images_the_qr_is_an_attachment_and_the_text_says_so() -> None:
    msg = _message()
    assert msg.get_content_type() == "multipart/mixed"
    attachment = next(msg.iter_attachments())
    assert attachment.get_filename() == "qr.png"
    assert attachment.get_content_type() == "image/png"
    assert attachment.get_content().startswith(b"\x89PNG")

    html = msg.get_body(preferencelist=("html",)).get_content()
    plain = msg.get_body(preferencelist=("plain",)).get_content()
    assert "cid:" not in html  # nothing that would show as a broken image
    assert "attached" in html and "attached" in plain
    assert TOKEN in html and TOKEN in plain  # the code is readable even if the file is not
    assert "&lt;b&gt;" in html  # a name cannot inject markup into the email


def test_inline_layout_is_unchanged_for_smtp() -> None:
    msg = build_message("registration_confirmed", _ctx(), 1, "a@b.co")
    assert msg is not None and msg.get_content_type() == "multipart/related"


def test_emails_without_a_qr_have_no_attachment() -> None:
    msg = build_message("registration_waitlisted", _ctx(), 1, "a@b.co", inline_qr=False)
    assert msg is not None and list(msg.iter_attachments()) == []


# ------------------------------------------------------------ the Brevo request


def test_payload_matches_brevos_api_shape() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"], seen["url"] = request.method, str(request.url)
        seen["api_key"] = request.headers["api-key"]
        seen["json"] = json.loads(request.content)
        return httpx.Response(201, json={"messageId": "<x@brevo>"})

    _sender(handler)(_message())

    assert (seen["method"], seen["url"]) == ("POST", "https://brevo.test/v3/smtp/email")
    assert seen["api_key"] == "secret-key"
    body = seen["json"]
    assert body["sender"] == {"email": "events@example.com", "name": "EntriX"}
    assert body["to"] == [{"email": "student@college.edu"}]
    assert body["subject"].startswith("You're in: Table Tennis")
    assert TOKEN in body["textContent"] and TOKEN in body["htmlContent"]
    assert body["headers"] == {"X-Entrix-Outbox-Id": "42"}
    (attachment,) = body["attachment"]
    assert attachment["name"] == "qr.png"
    assert base64.b64decode(attachment["content"]).startswith(b"\x89PNG")


def test_sender_without_a_display_name() -> None:
    body = Brevo.payload(_message("events@example.com"))
    assert body["sender"] == {"email": "events@example.com"}


def test_a_message_without_a_qr_sends_no_attachment_field() -> None:
    msg = build_message("registration_cancelled", _ctx(), 1, "a@b.co", inline_qr=False)
    assert "attachment" not in Brevo.payload(msg)


@pytest.mark.parametrize("status", [200, 201, 202])
def test_success_statuses(status: int) -> None:
    _sender(lambda r: httpx.Response(status, json={}))(_message())


def test_rate_limit_defers_instead_of_failing() -> None:
    with pytest.raises(DeferredError) as default:
        _sender(lambda r: httpx.Response(429, json={"code": "too_many_requests"}))(_message())
    assert default.value.delay_seconds == 3600 and "quota" in default.value.reason

    with pytest.raises(DeferredError) as asked:
        _sender(lambda r: httpx.Response(429, headers={"retry-after": "900"}))(_message())
    assert asked.value.delay_seconds == 900

    with pytest.raises(DeferredError) as silly:  # clamped to something sensible
        _sender(lambda r: httpx.Response(429, headers={"retry-after": "9999999"}))(_message())
    assert silly.value.delay_seconds == 6 * 60 * 60

    with pytest.raises(DeferredError) as junk:
        _sender(lambda r: httpx.Response(429, headers={"retry-after": "soon"}))(_message())
    assert junk.value.delay_seconds == 3600


@pytest.mark.parametrize("status", [401, 403])
def test_bad_credentials_defer_and_do_not_leak_the_key(
    status: int, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("ERROR")
    with pytest.raises(DeferredError) as exc:
        _sender(lambda r: httpx.Response(status, json={"message": "Key not found"}))(_message())
    assert exc.value.delay_seconds == 15 * 60
    assert "BREVO_API_KEY" in caplog.text
    assert "secret-key" not in caplog.text and "secret-key" not in exc.value.reason


@pytest.mark.parametrize("status", [400, 500, 503])
def test_other_errors_are_ordinary_failures_that_count_an_attempt(status: int) -> None:
    with pytest.raises(RuntimeError, match=str(status)):
        _sender(lambda r: httpx.Response(status, json={"message": "nope"}))(_message())


def test_network_errors_propagate_as_ordinary_failures() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    with pytest.raises(httpx.ConnectError):
        _sender(broken)(_message())


# ------------------------------------------------- the worker's handling of "not now"


class Deferring:
    inline_images = False

    def __init__(self, delay: int = 3600) -> None:
        self.calls = 0
        self.delay = delay

    def __call__(self, msg: Any) -> None:
        self.calls += 1
        raise DeferredError(self.delay, "daily quota used up")


async def _three_pending_emails(client: httpx.AsyncClient) -> None:
    event = await make_event(client)
    cid = (await make_category(client, event["id"], capacity=10))["id"]
    for i in range(3):
        r = await client.post(
            f"/categories/{cid}/registrations", headers={**as_user(f"u{i}@test.dev"), **idem()}
        )
        assert r.status_code == 201


async def _outbox() -> list[Any]:
    async with engine.connect() as conn:
        return list(
            (
                await conn.execute(
                    text(
                        "SELECT status::text AS status, attempts, last_error, "
                        "extract(epoch FROM next_attempt_at - now()) AS due_in "
                        "FROM outbox ORDER BY id"
                    )
                )
            ).all()
        )


async def test_a_quota_error_postpones_the_whole_batch_without_using_attempts(
    client: httpx.AsyncClient,
) -> None:
    await _three_pending_emails(client)
    provider = Deferring(delay=1800)

    assert await process_batch(SessionLocal, provider, max_attempts=3) == 3

    assert provider.calls == 1  # it did not keep hammering a provider that said "not now"
    rows = await _outbox()
    assert [r.status for r in rows] == ["pending"] * 3
    assert [r.attempts for r in rows] == [0, 0, 0]
    assert all(1700 < r.due_in <= 1800 for r in rows)
    assert "quota" in rows[0].last_error


async def test_repeated_quota_errors_never_turn_into_permanent_failures(
    client: httpx.AsyncClient,
) -> None:
    """The scenario this exists for: a launch bigger than the daily email cap."""
    await _three_pending_emails(client)
    provider = Deferring()
    for _ in range(12):  # far more rounds than max_attempts
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE outbox SET next_attempt_at = now()"))
        await process_batch(SessionLocal, provider, max_attempts=3)

    assert {r.status for r in await _outbox()} == {"pending"}
    assert {r.attempts for r in await _outbox()} == {0}

    # The next day the quota is back: everything goes out.
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE outbox SET next_attempt_at = now()"))
    working = Mailbox()
    await process_batch(SessionLocal, working, max_attempts=3)
    assert len(working.sent) == 3
    assert {r.status for r in await _outbox()} == {"sent"}


async def test_the_worker_hands_brevo_the_attachment_layout(client: httpx.AsyncClient) -> None:
    await _three_pending_emails(client)
    payloads: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(201, json={})

    await process_batch(SessionLocal, _sender(handler), max_attempts=3)

    assert len(payloads) == 3
    assert all("cid:" not in p["htmlContent"] for p in payloads)  # no broken inline image
    assert all(p["attachment"][0]["name"] == "qr.png" for p in payloads)
    assert {r.status for r in await _outbox()} == {"sent"}


async def test_a_genuine_failure_still_counts_attempts_and_ends_in_failed(
    client: httpx.AsyncClient,
) -> None:
    """Deferral is only for 'not now' errors; a real failure keeps the old behaviour."""
    await _three_pending_emails(client)
    sender = _sender(lambda r: httpx.Response(400, json={"message": "invalid sender"}))
    for _ in range(3):
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE outbox SET next_attempt_at = now()"))
        await process_batch(SessionLocal, sender, max_attempts=3)
    rows = await _outbox()
    assert {r.status for r in rows} == {"failed"} and {r.attempts for r in rows} == {3}
    assert "400" in rows[0].last_error
