"""End-to-end smoke test of a running EntriX API (the deployed one, or a local one).

    $env:ENTRIX_TOKEN = "<a fresh Clerk session token>"      # PowerShell
    python -m scripts.smoke_test_deployed https://your-service.onrender.com

Get the token from the test page (tools/clerk_test): sign in, click "Copy token", paste it into
the variable above. Tokens last about a minute, so run this straight away. The signed-in user
must be an `admin` or `organizer` (see DEPLOY.md, "Make your first organizer").

It walks one registration through its whole life: creates a draft event, publishes it, adds a
category, registers you, replays the same request (idempotency), tries a duplicate, reads the QR
token, scans it (and scans it again), tries to cancel after check-in, reads the organizer stats
and CSV, and finally closes the event. The registration queues a confirmation email: check your
inbox for "You're in: ... (SMOKE TEST ...)" afterwards, which this script cannot see.

It leaves one closed event named "SMOKE TEST <time>" behind (events have no delete endpoint).
"""

import asyncio
import os
import sys
import time
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

import httpx


class SmokeFailure(Exception):
    pass


HINTS = {
    "token_expired": "The token expired (they last about a minute). Copy a fresh one and rerun.",
    "invalid_auth_token": "The API rejected the token: check CLERK_ISSUER and CLERK_JWKS_URL.",
    "missing_email_claim": "Add the email claim to the Clerk session token (DEPLOY.md, section 1).",
    "unauthenticated": "No usable token was sent. Set ENTRIX_TOKEN to a fresh token.",
}


def _iso(delta: timedelta) -> str:
    return (datetime.now(UTC) + delta).isoformat()


async def run_smoke(
    client: httpx.AsyncClient, auth: dict[str, str], out: Callable[[str], None] = print
) -> bool:
    """Run every step; returns True if all passed. Prints one line per step."""
    count = 0

    def step(ok: bool, name: str, detail: str = "") -> None:
        nonlocal count
        count += 1
        suffix = f"  ({detail})" if detail else ""
        out(f"[{'OK' if ok else 'FAIL':>4}] {count:>2}. {name}{suffix}")
        if not ok:
            raise SmokeFailure(name)

    async def call(
        method: str,
        path: str,
        *,
        json: object = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        return await client.request(method, path, json=json, headers={**auth, **(headers or {})})

    def code_of(response: httpx.Response) -> str:
        try:
            return str(response.json()["error"]["code"])
        except (ValueError, KeyError, TypeError):
            return f"HTTP {response.status_code}"

    try:
        started = time.monotonic()
        live = await client.get("/livez")
        step(live.status_code == 200, "service is up", f"{time.monotonic() - started:.1f}s")

        me = await call("GET", "/me")
        if me.status_code != 200:
            hint = HINTS.get(code_of(me), "")
            step(False, "signed in (GET /me)", f"{me.status_code} {code_of(me)}. {hint}")
        role = me.json()["role"]
        step(True, "signed in (GET /me)", f"{me.json()['email']}, role {role}")
        step(
            role in ("admin", "organizer"),
            "has permission to create events",
            "" if role in ("admin", "organizer") else
            "run in Neon: UPDATE users SET role = 'admin' WHERE email = '<your email>';",
        )

        stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        created = await call(
            "POST",
            "/events",
            json={
                "slug": f"smoke-{uuid.uuid4().hex[:10]}",
                "name": f"SMOKE TEST {stamp}",
                "venue": "Smoke Ground",
                "starts_at": _iso(timedelta(days=2)),
                "ends_at": _iso(timedelta(days=3)),
                "reg_opens_at": _iso(timedelta(hours=-1)),
                "reg_closes_at": _iso(timedelta(days=1)),
            },
        )
        step(created.status_code == 201, "create a draft event", code_of(created))
        event_id = created.json()["id"]

        published = await call("PATCH", f"/events/{event_id}", json={"status": "published"})
        step(published.status_code == 200, "publish it", code_of(published))

        category = await call(
            "POST",
            f"/events/{event_id}/categories",
            json={
                "name": "Smoke Singles",
                "sport": "table-tennis",
                "participation": "individual",
                "capacity": 2,
            },
        )
        step(category.status_code == 201, "add a category (capacity 2)", code_of(category))
        category_id = category.json()["id"]

        public = await client.get(f"/events/{event_id}")
        seats = public.json()["categories"][0]["seats_left"] if public.status_code == 200 else None
        step(seats == 2, "the public page shows 2 seats left", f"seats_left={seats}")

        key = str(uuid.uuid4())
        path = f"/categories/{category_id}/registrations"
        first = await call("POST", path, headers={"Idempotency-Key": key})
        ok = first.status_code == 201 and first.json().get("status") == "confirmed"
        step(ok, "register: seat confirmed", code_of(first) if not ok else "201 confirmed")
        registration_id = first.json()["registration_id"]

        replay = await call("POST", path, headers={"Idempotency-Key": key})
        step(
            replay.status_code == 201 and replay.content == first.content,
            "same request again: identical stored response (idempotency)",
        )

        duplicate = await call("POST", path, headers={"Idempotency-Key": str(uuid.uuid4())})
        step(
            duplicate.status_code == 409 and code_of(duplicate) == "already_registered",
            "new request, same person: refused as already registered",
            code_of(duplicate),
        )

        mine = await call("GET", "/me/registrations")
        rows = [r for r in mine.json()["items"] if r["registration_id"] == registration_id]
        step(
            len(rows) == 1 and rows[0]["status"] == "confirmed",
            "it appears in my registrations as confirmed",
        )

        qr = await call("GET", f"/registrations/{registration_id}/qr")
        token = qr.json().get("token", "") if qr.status_code == 200 else ""
        step(token.startswith(registration_id + "."), "QR token issued", f"{len(token)} chars")

        scan = await call("POST", f"/events/{event_id}/check-in", json={"token": token})
        step(
            scan.status_code == 200 and scan.json()["already_checked_in"] is False,
            "scan the QR: checked in",
            code_of(scan) if scan.status_code != 200 else "",
        )
        again = await call("POST", f"/events/{event_id}/check-in", json={"token": token})
        step(
            again.status_code == 200 and again.json()["already_checked_in"] is True,
            "scan it again: safely reported as already checked in",
        )
        forged = await call(
            "POST", f"/events/{event_id}/check-in", json={"token": registration_id + ".forged"}
        )
        step(
            forged.status_code == 400 and code_of(forged) == "invalid_token",
            "a forged QR token is rejected",
            code_of(forged),
        )

        cancel = await call("DELETE", f"/registrations/{registration_id}")
        step(
            cancel.status_code == 409 and code_of(cancel) == "already_checked_in",
            "cancelling after check-in is refused",
            code_of(cancel),
        )

        stats = await call("GET", f"/events/{event_id}/stats")
        line = stats.json()["categories"][0] if stats.status_code == 200 else {}
        step(
            line.get("confirmed") == 1 and line.get("checked_in") == 1,
            "organizer stats: 1 confirmed, 1 checked in",
            str({k: line.get(k) for k in ("capacity", "confirmed", "waitlisted", "checked_in")}),
        )

        listing = await call("GET", f"/events/{event_id}/registrations")
        step(
            listing.status_code == 200 and len(listing.json()["items"]) == 1,
            "organizer list shows the registration",
        )
        export = await call("GET", f"/events/{event_id}/registrations.csv")
        lines = export.text.strip().splitlines() if export.status_code == 200 else []
        step(
            len(lines) == 2 and "checked_in" in lines[1],
            "CSV export: header plus one row",
            f"{len(lines)} lines",
        )

        closed = await call("PATCH", f"/events/{event_id}", json={"status": "closed"})
        step(closed.status_code == 200, "close the event (hides it from the public list)")

    except SmokeFailure as failure:
        out(f"\nStopped at: {failure}. Nothing after this step was run.")
        return False

    out(
        f"\nAll {count} steps passed. Event id: {event_id}\n"
        "Now check your inbox (and spam) for \"You're in: Smoke Singles (SMOKE TEST ...)\" "
        "from EntriX: the confirmation email with the QR code attached."
    )
    return True


async def amain(argv: Sequence[str]) -> int:
    base_url = next((a for a in argv if a.startswith("http")), "").rstrip("/")
    token = next((a for a in argv if not a.startswith("http") and len(a) > 40), None)
    token = token or os.environ.get("ENTRIX_TOKEN", "")
    if not base_url or not token:
        if not base_url:
            print("No service URL given: add it after the command, e.g. https://xxxx.onrender.com\n")
        if not token:
            print(
                "No token: the ENTRIX_TOKEN variable is empty (and none was passed).\n"
                "  1. On the test page (tools/clerk_test) click 'Copy: Remember the token ...'\n"
                "  2. Paste it into PowerShell: this sets $t\n"
                "  3. Then, within the minute:  $env:ENTRIX_TOKEN = $t\n"
            )
        print("Full instructions:\n" + (__doc__ or ""))
        return 2
    async with httpx.AsyncClient(base_url=base_url, timeout=90) as client:
        passed = await run_smoke(client, {"Authorization": f"Bearer {token}"})
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(amain(sys.argv[1:])))
