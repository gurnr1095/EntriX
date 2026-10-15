import csv
import io
import uuid
from typing import Any

import httpx
from sqlalchemy import text

from app.db import engine
from tests.conftest import (
    ORGANIZER,
    as_user,
    idem,
    make_category,
    make_event,
    make_team_category,
)
from tests.invariants import assert_invariants

VOLUNTEER = as_user("volunteer@test.dev", "volunteer")


async def _register(client: httpx.AsyncClient, cid: str, email: str) -> dict[str, Any]:
    r = await client.post(f"/categories/{cid}/registrations", headers={**as_user(email), **idem()})
    assert r.status_code == 201, r.text
    return r.json()


async def _seed(client: httpx.AsyncClient) -> dict[str, Any]:
    """Singles (cap 3): 5 people, so 3 confirmed + 2 waitlisted, one checked in.
    Cricket (cap 2): one registered team of 2."""
    event = await make_event(client)
    singles = await make_category(client, event["id"], capacity=3, name="Singles")
    cricket = await make_team_category(
        client, event["id"], capacity=2, team_min=2, team_max=2, name="Cricket"
    )
    regs = [await _register(client, singles["id"], f"p{i}@test.dev") for i in range(5)]

    team = (
        await client.post(
            f"/categories/{cricket['id']}/teams", json={"name": "Smashers"}, headers=as_user("cap@test.dev")
        )
    ).json()
    await client.post("/teams/join", json={"invite_code": team["invite_code"]}, headers=as_user("mate@test.dev"))
    team_reg = (
        await client.post(f"/teams/{team['id']}/register", headers={**as_user("cap@test.dev"), **idem()})
    ).json()

    token = (await client.get(f"/registrations/{regs[0]['registration_id']}/qr", headers=as_user("p0@test.dev"))).json()["token"]
    scan = await client.post(f"/events/{event['id']}/check-in", json={"token": token}, headers=VOLUNTEER)
    assert scan.status_code == 200
    return {"event": event, "singles": singles, "cricket": cricket, "regs": regs, "team_reg": team_reg}


async def test_list_registrations_with_filters(client: httpx.AsyncClient) -> None:
    s = await _seed(client)
    eid = s["event"]["id"]

    everything = (await client.get(f"/events/{eid}/registrations", headers=ORGANIZER)).json()
    assert len(everything["items"]) == 6 and everything["next_cursor"] is None
    created = [i["created_at"] for i in everything["items"]]
    assert created == sorted(created)

    by_status = {}
    for status in ("confirmed", "waitlisted", "checked_in", "cancelled"):
        page = (await client.get(f"/events/{eid}/registrations", params={"status": status}, headers=ORGANIZER)).json()
        by_status[status] = len(page["items"])
    assert by_status == {"confirmed": 3, "waitlisted": 2, "checked_in": 1, "cancelled": 0}

    cricket_only = (
        await client.get(f"/events/{eid}/registrations", params={"category_id": s["cricket"]["id"]}, headers=ORGANIZER)
    ).json()["items"]
    assert len(cricket_only) == 1
    row = cricket_only[0]
    assert row["team_name"] == "Smashers" and row["category_name"] == "Cricket"
    assert row["participant"]["email"] == "cap@test.dev"  # the captain holds the registration

    first = next(i for i in everything["items"] if i["participant"]["email"] == "p0@test.dev")
    assert first["status"] == "checked_in" and first["team_name"] is None
    assert set(first["participant"]) == {"id", "name", "email", "college", "roll_no", "phone"}


async def test_list_registrations_is_scoped_to_the_event(client: httpx.AsyncClient) -> None:
    s = await _seed(client)
    other = await make_event(client)
    other_cat = await make_category(client, other["id"], capacity=2, name="Elsewhere")
    await _register(client, other_cat["id"], "other@test.dev")

    items = (await client.get(f"/events/{s['event']['id']}/registrations", headers=ORGANIZER)).json()["items"]
    assert "other@test.dev" not in {i["participant"]["email"] for i in items}


async def test_pagination_walks_every_row_exactly_once(client: httpx.AsyncClient) -> None:
    s = await _seed(client)
    eid = s["event"]["id"]

    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, Any] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = (await client.get(f"/events/{eid}/registrations", params=params, headers=ORGANIZER)).json()
        seen += [i["registration_id"] for i in page["items"]]
        pages += 1
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert pages == 3 and len(seen) == 6 and len(set(seen)) == 6

    bad = await client.get(f"/events/{eid}/registrations", params={"cursor": "garbage"}, headers=ORGANIZER)
    assert bad.status_code == 422


async def test_stats(client: httpx.AsyncClient) -> None:
    s = await _seed(client)
    stats = (await client.get(f"/events/{s['event']['id']}/stats", headers=ORGANIZER)).json()["categories"]
    by_name = {c["name"]: c for c in stats}

    assert by_name["Singles"] == {
        "id": s["singles"]["id"], "name": "Singles", "capacity": 3,
        "confirmed": 3, "waitlisted": 2, "checked_in": 1,
    }  # `confirmed` counts the checked-in seat too, as in the SPEC example
    assert by_name["Cricket"]["confirmed"] == 1
    assert by_name["Cricket"]["waitlisted"] == 0 and by_name["Cricket"]["checked_in"] == 0

    # Cancellations move the numbers.
    await client.delete(f"/registrations/{s['regs'][1]['registration_id']}", headers=as_user("p1@test.dev"))
    after = {c["name"]: c for c in (await client.get(f"/events/{s['event']['id']}/stats", headers=ORGANIZER)).json()["categories"]}
    assert after["Singles"]["confirmed"] == 3 and after["Singles"]["waitlisted"] == 1
    await assert_invariants()


async def test_stats_includes_empty_categories(client: httpx.AsyncClient) -> None:
    event = await make_event(client)
    await make_category(client, event["id"], capacity=4, name="Empty")
    stats = (await client.get(f"/events/{event['id']}/stats", headers=ORGANIZER)).json()["categories"]
    assert [(c["capacity"], c["confirmed"], c["waitlisted"], c["checked_in"]) for c in stats] == [(4, 0, 0, 0)]


async def test_csv_export(client: httpx.AsyncClient) -> None:
    s = await _seed(client)
    eid = s["event"]["id"]

    r = await client.get(f"/events/{eid}/registrations.csv", headers=ORGANIZER)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 6
    assert set(rows[0]) == {
        "registration_id", "status", "category", "team", "name", "email",
        "college", "roll_no", "phone", "registered_at", "waitlisted_at",
    }
    assert {row["status"] for row in rows} == {"confirmed", "waitlisted", "checked_in"}
    team_row = next(row for row in rows if row["category"] == "Cricket")
    assert team_row["team"] == "Smashers"
    waitlisted = [row for row in rows if row["status"] == "waitlisted"]
    assert len(waitlisted) == 2 and all(row["waitlisted_at"] for row in waitlisted)

    filtered = await client.get(f"/events/{eid}/registrations.csv", params={"status": "waitlisted"}, headers=ORGANIZER)
    assert len(list(csv.DictReader(io.StringIO(filtered.text)))) == 2


async def test_csv_neutralises_spreadsheet_formulas(client: httpx.AsyncClient) -> None:
    event = await make_event(client)
    cat = await make_category(client, event["id"], capacity=5)
    evil = as_user("evil@test.dev")
    await _register(client, cat["id"], "evil@test.dev")
    await client.patch("/me", json={"name": '=HYPERLINK("http://evil.example","click")', "college": "+cmd|' /C calc'!A0"}, headers=evil)

    rows = list(csv.DictReader(io.StringIO((await client.get(f"/events/{event['id']}/registrations.csv", headers=ORGANIZER)).text)))
    assert rows[0]["name"].startswith("'=")  # a leading quote stops Excel/Sheets running it
    assert rows[0]["college"].startswith("'+")
    # The JSON list is data, not a spreadsheet: it stays untouched.
    item = (await client.get(f"/events/{event['id']}/registrations", headers=ORGANIZER)).json()["items"][0]
    assert item["participant"]["name"].startswith("=")


async def test_csv_streams_a_large_event(client: httpx.AsyncClient) -> None:
    event = await make_event(client)
    cat = await make_category(client, event["id"], capacity=5000)
    async with engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO users (auth_id, email, name)
            SELECT 'bulk:' || g, 'bulk' || g || '@test.dev', 'Bulk ' || g FROM generate_series(1, 1500) g
        """))
        await conn.execute(text("""
            INSERT INTO registrations (category_id, user_id, status)
            SELECT :c, id, 'confirmed' FROM users WHERE auth_id LIKE 'bulk:%'
        """), {"c": uuid.UUID(cat["id"])})
        await conn.execute(text("UPDATE categories SET confirmed_count = 1500 WHERE id = :c"), {"c": uuid.UUID(cat["id"])})

    r = await client.get(f"/events/{event['id']}/registrations.csv", headers=ORGANIZER)
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 1500 and len({row["registration_id"] for row in rows}) == 1500
    await assert_invariants()


async def test_unknown_event_returns_404(client: httpx.AsyncClient) -> None:
    missing = uuid.uuid4()
    for path in ("registrations", "registrations.csv", "stats"):
        r = await client.get(f"/events/{missing}/{path}", headers=ORGANIZER)
        assert r.status_code == 404, path
