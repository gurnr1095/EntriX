"""Create a published demo event with registration open, so the site has something to register for.

    $env:ENTRIX_TOKEN = "<a fresh Clerk session token>"      # PowerShell
    python -m scripts.seed_demo_event https://your-service.onrender.com

The signed-in user must be an `organizer` or `admin`. Get the token from the test page
(tools/clerk_test), as for the smoke test; tokens last about a minute.

It makes one event (open for a week, starting in a few days) with four categories chosen so every
button on the site can be tried: plenty of seats (Register), two seats (fill it and the next person
gets the waitlist), one seat with no waitlist (Full), and a team category (Create team / Join).
Events cannot be deleted through the API, so run it once; close the event later from the organizer
screen if you want it gone from the public list.
"""

import asyncio
import os
import sys
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

import httpx

CATEGORIES: list[dict[str, object]] = [
    {"name": "Table Tennis Singles", "sport": "table-tennis", "participation": "individual",
     "capacity": 32, "waitlist_enabled": True},
    {"name": "Chess Open", "sport": "chess", "participation": "individual",
     "capacity": 2, "waitlist_enabled": True},
    {"name": "Carrom Doubles Final", "sport": "carrom", "participation": "individual",
     "capacity": 1, "waitlist_enabled": False},
    {"name": "Cricket", "sport": "cricket", "participation": "team",
     "team_size_min": 2, "team_size_max": 4, "capacity": 8, "waitlist_enabled": True},
]


def _iso(delta: timedelta) -> str:
    return (datetime.now(UTC) + delta).isoformat()


async def seed(
    client: httpx.AsyncClient, auth: dict[str, str], out: Callable[[str], None] = print
) -> str | None:
    """Returns the new event id, or None if something failed (the reason is printed)."""

    async def call(method: str, path: str, body: object = None) -> httpx.Response:
        return await client.request(method, path, json=body, headers=auth)

    def why(r: httpx.Response) -> str:
        try:
            return f"{r.status_code} {r.json()['error']['code']}"
        except (ValueError, KeyError, TypeError):
            return f"HTTP {r.status_code}"

    me = await call("GET", "/me")
    if me.status_code != 200:
        out(f"Not signed in ({why(me)}). Copy a fresh token and run again: they last a minute.")
        return None
    if me.json()["role"] not in ("organizer", "admin"):
        out("Your account is not an organizer. In Neon run: "
            "UPDATE users SET role = 'organizer' WHERE email = '<your email>';")
        return None

    stamp = datetime.now(UTC).strftime("%d %b %Y")
    created = await call("POST", "/events", {
        "slug": f"demo-{uuid.uuid4().hex[:8]}",
        "name": f"Demo Sports Fest {stamp}",
        "description": "A demo event to try EntriX: register, join a waitlist, form a team.\n"
                       "Bring your college ID card.",
        "venue": "Main Ground",
        "starts_at": _iso(timedelta(days=5)),
        "ends_at": _iso(timedelta(days=6)),
        "reg_opens_at": _iso(timedelta(minutes=-5)),
        "reg_closes_at": _iso(timedelta(days=4)),
    })
    if created.status_code != 201:
        out(f"Could not create the event ({why(created)}).")
        return None
    event_id: str = created.json()["id"]

    for category in CATEGORIES:
        r = await call("POST", f"/events/{event_id}/categories", category)
        if r.status_code != 201:
            out(f"Could not add {category['name']} ({why(r)}). The event is still a draft.")
            return None
    published = await call("PATCH", f"/events/{event_id}", {"status": "published"})
    if published.status_code != 200:
        out(f"Could not publish the event ({why(published)}).")
        return None
    out(f"Created and published '{created.json()['name']}' with {len(CATEGORIES)} categories.")
    out(f"Open the site and look for it on the Events page. Event id: {event_id}")
    return event_id


async def amain(argv: Sequence[str]) -> int:
    base_url = next((a for a in argv if a.startswith("http")), "").rstrip("/")
    token = next((a for a in argv if not a.startswith("http") and len(a) > 40), None)
    token = token or os.environ.get("ENTRIX_TOKEN", "")
    if not base_url or not token:
        print(__doc__)
        return 2
    async with httpx.AsyncClient(base_url=base_url, timeout=90) as client:
        return 0 if await seed(client, {"Authorization": f"Bearer {token}"}) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(amain(sys.argv[1:])))
