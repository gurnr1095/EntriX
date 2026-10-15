"""The exact value that broke Render, and the plain-address + separate-name way out."""

from email.utils import parseaddr

import httpx
import pytest

from app.config import Settings, get_settings, sender_address, validate_worker_startup
from app.db import SessionLocal
from app.worker.outbox_worker import process_batch
from tests.conftest import as_user, idem, make_category, make_event
from tests.test_outbox_worker import Mailbox


def test_the_exact_value_that_broke_render_is_rejected() -> None:
    """Render's dashboard held `EntriX grkr1095@gmail.com`: no angle brackets, so no address."""
    assert sender_address("EntriX grkr1095@gmail.com") is None
    with pytest.raises(RuntimeError) as exc:
        validate_worker_startup(Settings(mail_from="EntriX grkr1095@gmail.com"))
    assert "'EntriX grkr1095@gmail.com'" in str(exc.value)  # it shows the value it received
    assert "MAIL_FROM_NAME" in str(exc.value)  # and points at the easier way


@pytest.mark.parametrize(
    "mail_from,name,expected",
    [
        ("grkr1095@gmail.com", "EntriX", "EntriX <grkr1095@gmail.com>"),  # the recommended way
        ("grkr1095@gmail.com", "", "grkr1095@gmail.com"),
        ("EntriX <grkr1095@gmail.com>", "", "EntriX <grkr1095@gmail.com>"),  # still works
        ("Old Name <grkr1095@gmail.com>", "EntriX", "EntriX <grkr1095@gmail.com>"),  # name wins
        ("grkr1095@gmail.com", '"EntriX"', "EntriX <grkr1095@gmail.com>"),  # stray quotes
        ("grkr1095@gmail.com", "Zeal, NIT Delhi", '"Zeal, NIT Delhi" <grkr1095@gmail.com>'),
    ],
)
def test_the_from_header_combines_a_plain_address_with_a_name(
    mail_from: str, name: str, expected: str
) -> None:
    header = Settings(mail_from=mail_from, mail_from_name=name).sender_header()
    assert header == expected
    assert sender_address(header) == "grkr1095@gmail.com"  # what Brevo is finally given
    clean_name = name.strip("\"'")
    if clean_name:
        assert parseaddr(header)[0] == clean_name  # the name survives a round trip


def test_an_unusable_sender_header_is_passed_through_for_the_startup_check_to_report() -> None:
    assert Settings(mail_from="oops").sender_header() == "oops"


async def test_emails_carry_the_combined_from_header(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "mail_from", "grkr1095@gmail.com")
    monkeypatch.setattr(settings, "mail_from_name", "EntriX")
    event = await make_event(client)
    cid = (await make_category(client, event["id"], capacity=2))["id"]
    r = await client.post(
        f"/categories/{cid}/registrations", headers={**as_user("n@test.dev"), **idem()}
    )
    assert r.status_code == 201

    box = Mailbox()
    await process_batch(SessionLocal, box)
    assert [m["From"] for m in box.sent] == ["EntriX <grkr1095@gmail.com>"]
