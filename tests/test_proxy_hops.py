"""The real header chain observed on Render's free tier (from the production log):

    x_forwarded_for = 'visitor, Cloudflare edge, Render's internal proxy'   (3 entries)
    socket address  = Render's internal proxy (a 10.x private address)

With TRUSTED_PROXY_HOPS=1 the app picked the internal proxy, so every visitor shared one
per-IP rate limit. The right value there is 3.
"""

import pytest
from starlette.requests import Request

from app.config import get_settings
from app.services.rate_limit import client_ip

VISITOR = "49.43.109.43"
CHAIN = f"{VISITOR}, 104.22.66.241, 10.26.96.152"
INTERNAL_PROXY = "10.26.96.152"


def _request(forwarded_for: str | None) -> Request:
    headers = [] if forwarded_for is None else [(b"x-forwarded-for", forwarded_for.encode())]
    return Request({"type": "http", "headers": headers, "client": (INTERNAL_PROXY, 0)})


@pytest.fixture
def hops(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    def apply(value: int) -> None:
        monkeypatch.setattr(get_settings(), "trusted_proxy_hops", value)

    return apply


def test_three_hops_finds_the_visitor_on_render(hops) -> None:  # type: ignore[no-untyped-def]
    hops(3)
    assert client_ip(_request(CHAIN)) == VISITOR


def test_a_forged_header_from_the_visitor_cannot_change_the_answer(hops) -> None:  # type: ignore[no-untyped-def]
    """Whatever the visitor sends lands on the LEFT; the proxies append on the right."""
    hops(3)
    forged = f"1.1.1.1, 2.2.2.2, {CHAIN}"
    assert client_ip(_request(forged)) == VISITOR


def test_one_hop_is_the_misconfiguration_that_was_live(hops) -> None:  # type: ignore[no-untyped-def]
    """Documented on purpose: this is what made every visitor look like one address."""
    hops(1)
    assert client_ip(_request(CHAIN)) == INTERNAL_PROXY


def test_two_hops_picks_a_cloudflare_address_and_is_also_wrong(hops) -> None:  # type: ignore[no-untyped-def]
    hops(2)
    assert client_ip(_request(CHAIN)) == "104.22.66.241"


def test_a_shorter_chain_than_expected_falls_back_to_the_socket_address(hops) -> None:  # type: ignore[no-untyped-def]
    """E.g. a request that did not come through the proxies: never trust a short header."""
    hops(3)
    assert client_ip(_request("1.1.1.1")) == INTERNAL_PROXY
    assert client_ip(_request(None)) == INTERNAL_PROXY
