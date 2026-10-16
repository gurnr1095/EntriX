"""M6a: what a browser client needs (CORS, names in "my registrations", my teams, organizer reads)."""

import uuid

import httpx
import pytest

from app.config import get_settings
from app.main import create_app
from tests.conftest import (
    ORGANIZER,
    as_user,
    idem,
    make_category,
    make_event,
    make_team_category,
)

ORIGIN = "https://entrix-web.example.com"


def _cors_client(monkeypatch: pytest.MonkeyPatch, origins: str, regex: str = "") -> httpx.AsyncClient:
    settings = get_settings()
    monkeypatch.setattr(settings, "cors_allow_origins", origins)
    monkeypatch.setattr(settings, "cors_allow_origin_regex", regex)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://test")


PREFLIGHT = {
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "authorization,idempotency-key,content-type",
}


async def test_preflight_for_an_allowed_origin_lists_the_headers_the_client_sends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _cors_client(monkeypatch, f"{ORIGIN}/, https://other.example.com") as c:
        r = await c.options(
            f"/categories/{uuid.uuid4()}/registrations", headers={"Origin": ORIGIN, **PREFLIGHT}
        )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == ORIGIN
    allowed = r.headers["access-control-allow-headers"].lower()
    assert "idempotency-key" in allowed and "authorization" in allowed
    assert "access-control-allow-credentials" not in r.headers  # bearer tokens, never cookies


async def test_an_unlisted_origin_gets_no_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _cors_client(monkeypatch, ORIGIN) as c:
        r = await c.options(
            f"/categories/{uuid.uuid4()}/registrations",
            headers={"Origin": "https://evil.example.com", **PREFLIGHT},
        )
        assert "access-control-allow-origin" not in r.headers
        r = await c.get("/events", headers={"Origin": "https://evil.example.com"})
        assert "access-control-allow-origin" not in r.headers


async def test_the_regex_covers_changing_preview_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _cors_client(monkeypatch, "", r"https://[a-z0-9-]+\.lovable\.app") as c:
        ok = await c.get("/events", headers={"Origin": "https://abc-123.lovable.app"})
        bad = await c.get("/events", headers={"Origin": "https://abc.lovable.app.evil.com"})
    assert ok.headers["access-control-allow-origin"] == "https://abc-123.lovable.app"
    assert "access-control-allow-origin" not in bad.headers


async def test_error_responses_and_exposed_headers_reach_the_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without CORS headers on a 404/409/429 the browser would show only 'network error'."""
    async with _cors_client(monkeypatch, ORIGIN) as c:
        r = await c.get(f"/events/{uuid.uuid4()}", headers={"Origin": ORIGIN})
    assert r.status_code == 404
    assert r.headers["access-control-allow-origin"] == ORIGIN
    exposed = {h.strip().lower() for h in r.headers["access-control-expose-headers"].split(",")}
    assert {"retry-after", "content-disposition", "x-cache"} <= exposed


async def test_without_settings_no_cors_headers_are_sent(client: httpx.AsyncClient) -> None:
    r = await client.get("/events", headers={"Origin": ORIGIN})
    assert "access-control-allow-origin" not in r.headers


# ---- GET /me/registrations carries names ----


async def test_my_registrations_include_event_category_and_team_names(
    client: httpx.AsyncClient,
) -> None:
    event = await make_event(client)
    single = await make_category(client, event["id"], capacity=5, name="Singles")
    team_cat = await make_team_category(client, event["id"], capacity=5, team_min=1, team_max=2)
    me = as_user("p@test.dev")
    assert (
        await client.post(
            f"/categories/{single['id']}/registrations", headers={**me, **idem()}
        )
    ).status_code == 201
    team = (
        await client.post(f"/categories/{team_cat['id']}/teams", json={"name": "Lions"}, headers=me)
    ).json()
    assert (
        await client.post(f"/teams/{team['id']}/register", headers={**me, **idem()})
    ).status_code == 201

    items = (await client.get("/me/registrations", headers=me)).json()["items"]
    by_cat = {i["category_name"]: i for i in items}
    solo, grp = by_cat["Singles"], by_cat["Cricket"]
    assert solo["event_id"] == event["id"] and solo["event_name"] == "Test Event"
    assert solo["sport"] == "table-tennis" and solo["team_id"] is None and solo["team_name"] is None
    assert solo["venue"] is None and solo["event_starts_at"].startswith(event["starts_at"][:16])
    assert grp["team_id"] == team["id"] and grp["team_name"] == "Lions"


async def test_my_registrations_still_report_waitlist_positions(client: httpx.AsyncClient) -> None:
    event = await make_event(client)
    cid = (await make_category(client, event["id"], capacity=1))["id"]
    for email in ("a@test.dev", "b@test.dev", "c@test.dev"):
        r = await client.post(
            f"/categories/{cid}/registrations", headers={**as_user(email), **idem()}
        )
        assert r.status_code == 201
    items = (await client.get("/me/registrations", headers=as_user("c@test.dev"))).json()["items"]
    assert [(i["status"], i["waitlist_position"]) for i in items] == [("waitlisted", 2)]
    assert items[0]["category_name"] == "Table Tennis Singles"


# ---- GET /me/teams ----


async def test_a_forming_team_survives_a_reload_and_only_the_captain_sees_the_code(
    client: httpx.AsyncClient,
) -> None:
    event = await make_event(client)
    cat = await make_team_category(client, event["id"], capacity=5, team_min=2, team_max=3)
    captain, mate = as_user("cap@test.dev"), as_user("mate@test.dev")
    team = (
        await client.post(f"/categories/{cat['id']}/teams", json={"name": "Hawks"}, headers=captain)
    ).json()

    mine = (await client.get("/me/teams", headers=captain)).json()
    assert len(mine) == 1
    t = mine[0]
    assert t["id"] == team["id"] and t["name"] == "Hawks" and t["status"] == "forming"
    assert t["invite_code"] == team["invite_code"] and t["is_captain"] is True
    assert (t["member_count"], t["team_size_min"], t["team_size_max"]) == (1, 2, 3)
    assert t["category_name"] == "Cricket" and t["event_id"] == event["id"]
    assert t["event_name"] == "Test Event"

    await client.post("/teams/join", json={"invite_code": team["invite_code"]}, headers=mate)
    theirs = (await client.get("/me/teams", headers=mate)).json()
    assert len(theirs) == 1
    assert theirs[0]["invite_code"] is None and theirs[0]["is_captain"] is False
    assert theirs[0]["member_count"] == 2
    assert (await client.get("/me/teams", headers=captain)).json()[0]["member_count"] == 2


async def test_my_teams_hides_other_peoples_and_cancelled_teams(client: httpx.AsyncClient) -> None:
    event = await make_event(client)
    cat = await make_team_category(client, event["id"], capacity=5, team_min=1, team_max=3)
    team = (
        await client.post(
            f"/categories/{cat['id']}/teams", json={"name": "Owls"}, headers=as_user("a@test.dev")
        )
    ).json()
    assert (await client.get("/me/teams", headers=as_user("stranger@test.dev"))).json() == []
    assert (await client.delete(f"/teams/{team['id']}", headers=as_user("a@test.dev"))).status_code == 200
    assert (await client.get("/me/teams", headers=as_user("a@test.dev"))).json() == []


async def test_my_teams_requires_authentication(client: httpx.AsyncClient) -> None:
    assert (await client.get("/me/teams")).status_code == 401


# ---- organizer reads ----


async def test_organizers_see_draft_events_that_the_public_cannot(client: httpx.AsyncClient) -> None:
    draft = await make_event(client, publish=False)
    live = await make_event(client)
    await make_category(client, draft["id"], capacity=3, name="Hidden")

    assert (await client.get(f"/events/{draft['id']}")).status_code == 404
    public_ids = {e["id"] for e in (await client.get("/events")).json()["items"]}
    assert public_ids == {live["id"]}

    listing = (await client.get("/organizer/events", headers=ORGANIZER)).json()
    assert {e["id"] for e in listing} == {draft["id"], live["id"]}
    detail = (await client.get(f"/organizer/events/{draft['id']}", headers=ORGANIZER)).json()
    assert detail["status"] == "draft"
    assert [c["name"] for c in detail["categories"]] == ["Hidden"]
    assert detail["categories"][0]["seats_left"] == 3

    # reading it as an organizer must not have put it in the public cache
    assert (await client.get(f"/events/{draft['id']}")).status_code == 404


async def test_organizer_reads_are_organizer_only_and_404_cleanly(client: httpx.AsyncClient) -> None:
    event = await make_event(client)
    for path in ("/organizer/events", f"/organizer/events/{event['id']}"):
        assert (await client.get(path)).status_code == 401
        assert (await client.get(path, headers=as_user("p@test.dev"))).status_code == 403
        assert (await client.get(path, headers=as_user("v@test.dev", "volunteer"))).status_code == 403
    missing = await client.get(f"/organizer/events/{uuid.uuid4()}", headers=ORGANIZER)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
