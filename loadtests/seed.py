"""Create the data a load test browses and registers against, before any traffic starts.

    python -m loadtests.seed <output.json> [--host http://localhost:8000]

Ten published events with three categories each; the first event's first category is the
"hot" one every launch-spike user registers for. Written to a JSON file that locustfile.py
reads, so Locust never starts sending traffic until seeding is finished.
"""

import argparse
import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import requests

HOT_CAPACITY = int(os.environ.get("LT_HOT_CAPACITY", "500"))
EVENT_COUNT = 10
ORGANIZER = {"X-Dev-User": "loadtest-organizer@load.test", "X-Dev-Role": "organizer"}


def _iso(delta: timedelta) -> str:
    return (datetime.now(UTC) + delta).isoformat()


def seed(host: str) -> dict[str, object]:
    host = host.rstrip("/")
    http = requests.Session()
    http.headers.update(ORGANIZER)
    run_id = uuid.uuid4().hex[:8]
    event_ids: list[str] = []
    hot_category = ""
    for i in range(EVENT_COUNT):
        event = http.post(
            f"{host}/events",
            json={
                "slug": f"load-{run_id}-{i}",
                "name": f"Load Test Event {i}",
                "venue": "Main Ground",
                "starts_at": _iso(timedelta(days=2)),
                "ends_at": _iso(timedelta(days=3)),
                "reg_opens_at": _iso(timedelta(hours=-1)),
                "reg_closes_at": _iso(timedelta(days=1)),
            },
        )
        event.raise_for_status()
        event_id = event.json()["id"]
        http.patch(f"{host}/events/{event_id}", json={"status": "published"}).raise_for_status()
        hot_capacity = HOT_CAPACITY if i == 0 else 100
        for name, capacity in (("Table Tennis", hot_capacity), ("Chess", 64), ("Badminton", 32)):
            category = http.post(
                f"{host}/events/{event_id}/categories",
                json={
                    "name": name,
                    "sport": name.lower(),
                    "participation": "individual",
                    "capacity": capacity,
                },
            )
            category.raise_for_status()
            if i == 0 and name == "Table Tennis":
                hot_category = category.json()["id"]
        event_ids.append(event_id)
    return {
        "run_id": run_id,
        "event_ids": event_ids,
        "hot_category": hot_category,
        "hot_capacity": HOT_CAPACITY,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output")
    parser.add_argument("--host", default="http://localhost:8000")
    args = parser.parse_args()
    data = seed(args.host)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"seeded {len(data['event_ids'])} events; hot category {data['hot_category']}")  # type: ignore[arg-type]
