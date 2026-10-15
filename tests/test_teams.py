import asyncio
from datetime import timedelta
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


async def _scalar(sql: str, **params: object) -> Any:
    async with engine.connect() as conn:
        return await conn.scalar(text(sql), params)


async def _team_category(
    client: httpx.AsyncClient, *, capacity: int = 5, team_min: int = 2, team_max: int = 3, **kw: Any
) -> tuple[str, str]:
    """Returns (event_id, category_id) for an open event with one team category."""
    event = await make_event(client)
    cat = await make_team_category(
        client, event["id"], capacity=capacity, team_min=team_min, team_max=team_max, **kw
    )
    return event["id"], cat["id"]


async def _create(client: httpx.AsyncClient, cid: str, email: str, name: str) -> dict[str, Any]:
    r = await client.post(f"/categories/{cid}/teams", json={"name": name}, headers=as_user(email))
    assert r.status_code == 201, r.text
    return r.json()


async def _join(client: httpx.AsyncClient, code: str, email: str) -> httpx.Response:
    return await client.post("/teams/join", json={"invite_code": code}, headers=as_user(email))


async def _register(client: httpx.AsyncClient, team_id: str, email: str) -> httpx.Response:
    return await client.post(
        f"/teams/{team_id}/register", headers={**as_user(email), **idem()}
    )


async def _full_team(
    client: httpx.AsyncClient, cid: str, name: str, extra_members: int = 1
) -> dict[str, Any]:
    """A team of captain + `extra_members`, captain is `<name>-cap@test.dev`."""
    team = await _create(client, cid, f"{name}-cap@test.dev", name)
    for i in range(extra_members):
        assert (await _join(client, team["invite_code"], f"{name}-m{i}@test.dev")).status_code == 200
    return {**team, "captain": f"{name}-cap@test.dev"}


# ---------------------------------------------------------------- test 10


async def test_10_team_size_bounds(client: httpx.AsyncClient) -> None:
    _, cid = await _team_category(client, team_min=2, team_max=3)
    team = await _create(client, cid, "cap@test.dev", "Bounds")
    assert team["status"] == "forming"
    assert len(team["invite_code"]) == 8

    too_small = await _register(client, team["id"], "cap@test.dev")
    assert too_small.status_code == 409
    assert too_small.json()["error"]["code"] == "team_size_invalid"

    for i in range(2):
        assert (await _join(client, team["invite_code"], f"m{i}@test.dev")).status_code == 200
    too_big = await _join(client, team["invite_code"], "m2@test.dev")  # 4th member, max is 3
    assert too_big.status_code == 409
    assert too_big.json()["error"]["code"] == "team_full"
    assert await _scalar("SELECT count(*) FROM team_members") == 3

    ok = await _register(client, team["id"], "cap@test.dev")
    assert ok.status_code == 201
    assert ok.json()["status"] == "confirmed"
    await assert_invariants()


async def test_10_user_cannot_join_two_teams_in_one_category(client: httpx.AsyncClient) -> None:
    _, cid = await _team_category(client)
    team_a = await _create(client, cid, "a-cap@test.dev", "Alpha")
    team_b = await _create(client, cid, "b-cap@test.dev", "Beta")
    assert (await _join(client, team_a["invite_code"], "shared@test.dev")).status_code == 200

    again = await _join(client, team_b["invite_code"], "shared@test.dev")
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "already_in_team"

    same_twice = await _join(client, team_a["invite_code"], "shared@test.dev")
    assert same_twice.json()["error"]["code"] == "already_in_team"

    # A captain cannot start a second team, and a member cannot start one either.
    for who in ("a-cap@test.dev", "shared@test.dev"):
        r = await client.post(f"/categories/{cid}/teams", json={"name": "Gamma"}, headers=as_user(who))
        assert r.status_code == 409 and r.json()["error"]["code"] == "already_in_team"

    # The restriction is per category: the same user can join a team elsewhere.
    event = await make_event(client)
    other = (await make_team_category(client, event["id"], capacity=2, name="Hockey"))["id"]
    await _create(client, other, "shared@test.dev", "Elsewhere")
    await assert_invariants()


async def test_10_roster_is_locked_after_registration(client: httpx.AsyncClient) -> None:
    _, cid = await _team_category(client)
    team = await _full_team(client, cid, "Locked")
    assert (await _register(client, team["id"], team["captain"])).status_code == 201
    assert await _scalar("SELECT status FROM teams WHERE id = :t", t=team["id"]) == "registered"

    late = await _join(client, team["invite_code"], "latecomer@test.dev")
    assert late.status_code == 409 and late.json()["error"]["code"] == "roster_locked"

    leave = await client.delete(
        f"/teams/{team['id']}/members/me", headers=as_user("Locked-m0@test.dev")
    )
    assert leave.status_code == 409 and leave.json()["error"]["code"] == "roster_locked"
    assert await _scalar("SELECT count(*) FROM team_members") == 2

    again = await _register(client, team["id"], team["captain"])  # fresh key
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_registered"
    await assert_invariants()


async def test_10_cancelling_a_team_frees_its_members(client: httpx.AsyncClient) -> None:
    _, cid = await _team_category(client, capacity=2)
    team = await _full_team(client, cid, "Doomed")
    reg = (await _register(client, team["id"], team["captain"])).json()
    assert await _scalar("SELECT confirmed_count FROM categories WHERE id = :c", c=cid) == 1

    stranger = await client.delete(f"/teams/{team['id']}", headers=as_user("nobody@test.dev"))
    assert stranger.status_code == 403
    member = await client.delete(f"/teams/{team['id']}", headers=as_user("Doomed-m0@test.dev"))
    assert member.status_code == 403  # only the captain or an organizer

    r = await client.delete(f"/teams/{team['id']}", headers=as_user(team["captain"]))
    assert r.status_code == 200 and r.json()["status"] == "cancelled"

    assert await _scalar("SELECT count(*) FROM team_members WHERE team_id = :t", t=team["id"]) == 0
    assert await _scalar("SELECT status FROM registrations WHERE id = :r", r=reg["registration_id"]) == "cancelled"
    assert await _scalar("SELECT confirmed_count FROM categories WHERE id = :c", c=cid) == 0
    assert await _scalar("SELECT count(*) FROM outbox WHERE event_type = 'registration_cancelled'") == 1

    # Freed: the former members can form and join new teams in this category.
    fresh = await _create(client, cid, "Doomed-m0@test.dev", "Phoenix")
    assert (await _join(client, fresh["invite_code"], "Doomed-cap@test.dev")).status_code == 200
    again = await client.delete(f"/teams/{team['id']}", headers=as_user(team["captain"]))
    assert again.status_code == 409
    await assert_invariants()


async def test_organizer_can_cancel_a_forming_team(client: httpx.AsyncClient) -> None:
    _, cid = await _team_category(client)
    team = await _full_team(client, cid, "Forming")
    r = await client.delete(f"/teams/{team['id']}", headers=ORGANIZER)
    assert r.status_code == 200
    assert await _scalar("SELECT count(*) FROM team_members") == 0
    assert await _scalar("SELECT count(*) FROM registrations") == 0
    await assert_invariants()


async def test_cancelling_the_registration_cancels_the_team(client: httpx.AsyncClient) -> None:
    _, cid = await _team_category(client)
    team = await _full_team(client, cid, "Cascade")
    reg = (await _register(client, team["id"], team["captain"])).json()

    r = await client.delete(
        f"/registrations/{reg['registration_id']}", headers=as_user(team["captain"])
    )
    assert r.status_code == 200
    assert await _scalar("SELECT status FROM teams WHERE id = :t", t=team["id"]) == "cancelled"
    assert await _scalar("SELECT count(*) FROM team_members") == 0
    await assert_invariants()


async def test_member_can_leave_a_forming_team_but_the_captain_cannot(
    client: httpx.AsyncClient,
) -> None:
    _, cid = await _team_category(client)
    team = await _full_team(client, cid, "Leavers")

    captain = await client.delete(f"/teams/{team['id']}/members/me", headers=as_user(team["captain"]))
    assert captain.status_code == 409
    assert captain.json()["error"]["code"] == "captain_cannot_leave"

    out = await client.delete(f"/teams/{team['id']}/members/me", headers=as_user("Leavers-m0@test.dev"))
    assert out.status_code == 204
    assert await _scalar("SELECT count(*) FROM team_members") == 1

    stranger = await client.delete(f"/teams/{team['id']}/members/me", headers=as_user("x@test.dev"))
    assert stranger.status_code == 403

    # Having left, they can join again, or another team.
    assert (await _join(client, team["invite_code"], "Leavers-m0@test.dev")).status_code == 200


async def test_team_rules_around_names_codes_and_category_kind(client: httpx.AsyncClient) -> None:
    event_id, cid = await _team_category(client)
    team = await _create(client, cid, "one@test.dev", "Same Name")

    dup = await client.post(f"/categories/{cid}/teams", json={"name": "Same Name"}, headers=as_user("two@test.dev"))
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "team_name_taken"

    assert (await _join(client, "NOSUCHCD", "two@test.dev")).status_code == 404
    lower = await _join(client, team["invite_code"].lower(), "two@test.dev")
    assert lower.status_code == 200  # codes are case-insensitive

    individual = await make_category(client, event_id, capacity=5, name="Singles")
    r = await client.post(f"/categories/{individual['id']}/teams", json={"name": "T"}, headers=as_user("x@test.dev"))
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_team_category"

    solo = await client.post(f"/categories/{cid}/registrations", headers={**as_user("x@test.dev"), **idem()})
    assert solo.status_code == 409 and solo.json()["error"]["code"] == "not_individual_category"


async def test_team_actions_need_an_open_registration_window(client: httpx.AsyncClient) -> None:
    event = await make_event(client, opens=timedelta(hours=1), closes=timedelta(hours=2))
    cid = (await make_team_category(client, event["id"], capacity=2))["id"]
    r = await client.post(f"/categories/{cid}/teams", json={"name": "Early"}, headers=as_user("e@test.dev"))
    assert r.status_code == 409 and r.json()["error"]["code"] == "registration_closed"


async def test_only_the_captain_registers_and_retries_are_idempotent(
    client: httpx.AsyncClient,
) -> None:
    _, cid = await _team_category(client)
    team = await _full_team(client, cid, "Idem")

    member = await _register(client, team["id"], "Idem-m0@test.dev")
    assert member.status_code == 403

    missing = await client.post(f"/teams/{team['id']}/register", headers=as_user(team["captain"]))
    assert missing.status_code == 400

    headers = {**as_user(team["captain"]), "Idempotency-Key": "team-key"}
    responses = await asyncio.gather(
        *(client.post(f"/teams/{team['id']}/register", headers=headers) for _ in range(10))
    )
    assert {r.status_code for r in responses} == {201}
    assert len({r.content for r in responses}) == 1
    assert await _scalar("SELECT count(*) FROM registrations") == 1
    assert await _scalar("SELECT user_id::text FROM registrations") == await _scalar(
        "SELECT captain_id::text FROM teams"
    )  # the captain holds the registration
    await assert_invariants()


async def test_team_waitlist_and_promotion(client: httpx.AsyncClient) -> None:
    _, cid = await _team_category(client, capacity=1)
    first = await _full_team(client, cid, "First")
    second = await _full_team(client, cid, "Second")
    third = await _full_team(client, cid, "Third")

    r1 = (await _register(client, first["id"], first["captain"])).json()
    r2 = (await _register(client, second["id"], second["captain"])).json()
    r3 = (await _register(client, third["id"], third["captain"])).json()
    assert [r1["status"], r2["status"], r3["status"]] == ["confirmed", "waitlisted", "waitlisted"]
    assert (r2["waitlist_position"], r3["waitlist_position"]) == (1, 2)
    # A waitlisted team is already `registered`: its roster is locked too.
    assert await _scalar("SELECT status FROM teams WHERE id = :t", t=second["id"]) == "registered"

    cancel = await client.delete(f"/teams/{first['id']}", headers=as_user(first["captain"]))
    assert cancel.status_code == 200

    assert await _scalar("SELECT status FROM registrations WHERE id = :r", r=r2["registration_id"]) == "confirmed"
    assert await _scalar("SELECT status FROM registrations WHERE id = :r", r=r3["registration_id"]) == "waitlisted"
    promoted = await _scalar("SELECT payload->>'user_id' FROM outbox WHERE event_type = 'waitlist_promoted'")
    assert promoted == await _scalar("SELECT captain_id::text FROM teams WHERE id = :t", t=second["id"])
    await assert_invariants()


async def test_team_detail_visibility(client: httpx.AsyncClient) -> None:
    _, cid = await _team_category(client)
    team = await _full_team(client, cid, "Peek")

    cap = (await client.get(f"/teams/{team['id']}", headers=as_user(team["captain"]))).json()
    assert cap["invite_code"] == team["invite_code"]
    assert [m["is_captain"] for m in cap["members"]] == [True, False]

    member = (await client.get(f"/teams/{team['id']}", headers=as_user("Peek-m0@test.dev"))).json()
    assert member["invite_code"] is None and len(member["members"]) == 2

    assert (await client.get(f"/teams/{team['id']}", headers=as_user("x@test.dev"))).status_code == 403
    org = (await client.get(f"/teams/{team['id']}", headers=ORGANIZER)).json()
    assert org["invite_code"] == team["invite_code"]


# ------------------------------------------------------------ concurrency


async def test_concurrent_joins_never_exceed_the_maximum(client: httpx.AsyncClient) -> None:
    _, cid = await _team_category(client, team_min=2, team_max=11)
    team = await _create(client, cid, "cap@test.dev", "Crowd")

    results = await asyncio.gather(
        *(_join(client, team["invite_code"], f"j{i}@test.dev") for i in range(30))
    )
    ok = [r for r in results if r.status_code == 200]
    full = [r for r in results if r.status_code == 409]
    assert len(ok) == 10 and len(full) == 20
    assert {r.json()["error"]["code"] for r in full} == {"team_full"}
    assert await _scalar("SELECT count(*) FROM team_members WHERE team_id = :t", t=team["id"]) == 11
    await assert_invariants()


async def test_one_user_racing_to_join_many_teams_gets_exactly_one(
    client: httpx.AsyncClient,
) -> None:
    _, cid = await _team_category(client)
    teams = [await _create(client, cid, f"c{i}@test.dev", f"Team{i}") for i in range(8)]

    results = await asyncio.gather(
        *(_join(client, t["invite_code"], "greedy@test.dev") for t in teams)
    )
    assert sorted(r.status_code for r in results) == [200] + [409] * 7
    assert await _scalar("SELECT count(*) FROM team_members WHERE user_id = (SELECT id FROM users WHERE email = 'greedy@test.dev')") == 1
    await assert_invariants()


async def test_joins_racing_a_registration_leave_a_consistent_roster(
    client: httpx.AsyncClient,
) -> None:
    _, cid = await _team_category(client, team_min=2, team_max=5)
    team = await _full_team(client, cid, "Race")  # 2 members

    register = _register(client, team["id"], team["captain"])
    joins = [_join(client, team["invite_code"], f"racer{i}@test.dev") for i in range(10)]
    reg_resp, *join_resps = await asyncio.gather(register, *joins)

    assert reg_resp.status_code == 201
    joined = [r for r in join_resps if r.status_code == 200]
    refused = [r for r in join_resps if r.status_code == 409]
    assert len(joined) + len(refused) == 10
    assert {r.json()["error"]["code"] for r in refused} <= {"roster_locked", "team_full"}
    members = await _scalar("SELECT count(*) FROM team_members WHERE team_id = :t", t=team["id"])
    assert members == 2 + len(joined) <= 5
    assert await _scalar("SELECT status FROM teams WHERE id = :t", t=team["id"]) == "registered"
    await assert_invariants()


async def test_many_teams_compete_for_few_seats(client: httpx.AsyncClient) -> None:
    _, cid = await _team_category(client, capacity=5, team_min=2, team_max=2)
    teams = [await _full_team(client, cid, f"T{i}") for i in range(20)]

    results = await asyncio.gather(*(_register(client, t["id"], t["captain"]) for t in teams))
    assert {r.status_code for r in results} == {201}
    statuses = [r.json()["status"] for r in results]
    assert statuses.count("confirmed") == 5 and statuses.count("waitlisted") == 15
    assert sorted(r.json()["waitlist_position"] for r in results if r.json()["status"] == "waitlisted") == list(range(1, 16))
    assert await _scalar("SELECT confirmed_count FROM categories WHERE id = :c", c=cid) == 5
    await assert_invariants()


async def test_full_team_category_without_waitlist_leaves_teams_registrable(
    client: httpx.AsyncClient,
) -> None:
    _, cid = await _team_category(client, capacity=3, team_min=2, team_max=2, waitlist_enabled=False)
    teams = [await _full_team(client, cid, f"N{i}") for i in range(10)]

    results = await asyncio.gather(*(_register(client, t["id"], t["captain"]) for t in teams))
    codes = sorted(r.status_code for r in results)
    assert codes == [201] * 3 + [409] * 7
    assert {r.json()["error"]["code"] for r in results if r.status_code == 409} == {"category_full"}
    # The 7 rejected teams were not touched: still forming, rosters intact.
    assert await _scalar("SELECT count(*) FROM teams WHERE status = 'forming'") == 7
    assert await _scalar("SELECT count(*) FROM team_members") == 20
    await assert_invariants()
