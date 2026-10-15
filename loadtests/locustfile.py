"""Load test scenarios (SPEC 7).

* Browse (about 80% of traffic): GET /events and GET /events/{id}.
* Launch spike (about 20%): unique users registering for one hot category.
* Shape: ramp from 0 to LT_PEAK_USERS over LT_RAMP_SECONDS, then hold until LT_RUN_SECONDS.

Run it with `python -m loadtests.run_loadtest`, which seeds the data (loadtests/seed.py),
resets the database, starts the API in a known configuration and checks the invariants
afterwards. LT_SEED_FILE points at the JSON that seed.py wrote.
"""

import itertools
import json
import math
import os
import random
import uuid

from locust import HttpUser, LoadTestShape, between, task

PEAK_USERS = int(os.environ.get("LT_PEAK_USERS", "300"))
RAMP_SECONDS = int(os.environ.get("LT_RAMP_SECONDS", "30"))
RUN_SECONDS = int(os.environ.get("LT_RUN_SECONDS", "120"))

with open(os.environ["LT_SEED_FILE"], encoding="utf-8") as _f:  # fail loudly if not seeded
    SEED = json.load(_f)
EVENT_IDS: list[str] = SEED["event_ids"]
HOT_CATEGORY: str = SEED["hot_category"]
RUN_ID: str = SEED["run_id"]
_counter = itertools.count(1)


class Browse(HttpUser):
    """A visitor looking around: mostly event pages, sometimes the list."""

    weight = 4
    wait_time = between(0.5, 1.5)

    @task(3)
    def list_events(self) -> None:
        self.client.get("/events", name="GET /events")

    @task(7)
    def event_detail(self) -> None:
        self.client.get(f"/events/{random.choice(EVENT_IDS)}", name="GET /events/{id}")


class Launch(HttpUser):
    """Someone trying to grab a seat the moment registration opens (a new person each time)."""

    weight = 1
    wait_time = between(0.5, 1.5)

    @task
    def register(self) -> None:
        email = f"lt{RUN_ID}-{next(_counter)}@load.test"
        with self.client.post(
            f"/categories/{HOT_CATEGORY}/registrations",
            headers={"X-Dev-User": email, "Idempotency-Key": str(uuid.uuid4())},
            name="POST /categories/{id}/registrations",
            catch_response=True,
        ) as response:
            if response.status_code == 201:
                response.success()
            else:
                response.failure(f"{response.status_code}: {response.text[:120]}")


class Spike(LoadTestShape):
    """0 -> PEAK_USERS over RAMP_SECONDS, then hold until RUN_SECONDS."""

    def tick(self) -> tuple[int, float] | None:
        t = self.get_run_time()
        if t >= RUN_SECONDS:
            return None
        users = max(1, math.ceil(PEAK_USERS * min(1.0, t / RAMP_SECONDS)))
        return users, PEAK_USERS / RAMP_SECONDS
