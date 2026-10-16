"""The demo-event script, proven against the real app before it touches production."""

import httpx

from app.main import app
from scripts.seed_demo_event import CATEGORIES, amain, seed
from tests.conftest import as_user, idem


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=60)


async def test_creates_a_published_open_event_every_button_can_be_tried_on() -> None:
    lines: list[str] = []
    async with _client() as client:
        event_id = await seed(client, as_user("org@test.dev", "organizer"), lines.append)
        assert event_id, lines

        listed = (await client.get("/events")).json()["items"]
        assert [e["id"] for e in listed] == [event_id]  # public, and the only one
        detail = (await client.get(f"/events/{event_id}")).json()
        assert {c["name"] for c in detail["categories"]} == {str(c["name"]) for c in CATEGORIES}

        # open for registration right now, so a student can really register
        by_name = {c["name"]: c for c in detail["categories"]}
        r = await client.post(
            f"/categories/{by_name['Table Tennis Singles']['id']}/registrations",
            headers={**as_user("student@test.dev"), **idem()},
        )
        assert r.status_code == 201 and r.json()["status"] == "confirmed"

        # the 1-seat, no-waitlist category really shows Full after one registration
        solo = by_name["Carrom Doubles Final"]["id"]
        for email, expected in (("a@test.dev", 201), ("b@test.dev", 409)):
            r = await client.post(
                f"/categories/{solo}/registrations", headers={**as_user(email), **idem()}
            )
            assert r.status_code == expected, r.text


async def test_a_participant_gets_the_fix_spelled_out_and_nothing_is_created() -> None:
    lines: list[str] = []
    async with _client() as client:
        assert await seed(client, as_user("student@test.dev"), lines.append) is None
        assert (await client.get("/events")).json()["items"] == []
    assert "UPDATE users SET role" in lines[0]


async def test_without_a_token_it_explains_itself() -> None:
    assert await amain(["https://example.onrender.com"]) == 2
