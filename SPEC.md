# SportReg: Sports Event Registration Platform (SPEC)

Working name `EntriX`. Rename freely. Built for college sports events (e.g. ITUSA, intra-college Zeal) where hundreds of students register in a short launch window, seats are limited per sport category, and entry-day check-in is chaotic.

This file is the single source of truth. Section 12 contains a `CLAUDE.md` to paste into the repo root, and section 13 contains the first prompt for Claude Code.

---

## 0. Decisions and assumptions (change these before building if you disagree)

1. **Scope:** sports events with individual categories (Table Tennis Singles) and team categories (Cricket, Indoor sports). Hackathon team flow reuses the same team logic later.
2. **No Celery or message broker.** The transactional outbox is polled by a small worker process. Redis is used only for rate limiting and caching in a later milestone.
3. **SQLAlchemy 2.0 async + asyncpg**, Alembic migrations, PostgreSQL 16.
4. **Auth:** Clerk JWT verification (JWKS) in production. In local/test mode (`AUTH_MODE=dev`) a header `X-Dev-User: <email>` selects a user. The app must refuse to start with `AUTH_MODE=dev` when `ENV=prod`.
5. **Frontend comes last.** Build and test the backend first. The frontend is a thin React + TypeScript client.
6. **Tests run against real PostgreSQL**, never SQLite. Concurrency semantics are the whole point.
7. **Stretch (default OFF):** fixture/bracket generation and Elo ranking. Only start it after M5.
8. All the steps and changes should be documented in a decisions.md document in easy-to-understand language for interview based questions that might be asked for this project.

---

## 1. Goals and non-goals

**Goals**
- Never overbook a category, even under hundreds of simultaneous requests.
- A retried or double-clicked request never creates two registrations.
- Fair, race-safe waitlist with automatic promotion on cancellation.
- No confirmed seat without a queued confirmation email, and no email for a seat that was rolled back.
- Forgery-proof QR check-in that is safe to scan twice.
- Measured, honest performance numbers.

**Non-goals**
- Payments, Kubernetes, microservices, Kafka, a mobile app, or an AI feature. None of these helps the project's purpose, and each adds scope.

---

## 2. Tech stack

| Layer | Choice |
|---|---|
| API | FastAPI, Pydantic v2 |
| DB | PostgreSQL 16, SQLAlchemy 2.0 (async), asyncpg, Alembic |
| Auth | Clerk JWT (JWKS) + dev mode for tests |
| Worker | Plain Python process polling the `outbox` table |
| Cache / rate limit | Redis 7 (M5), in-memory fallback for tests |
| Email | SMTP (MailHog in dev) |
| Tests | pytest, pytest-asyncio, httpx AsyncClient |
| Load test | Locust |
| Lint / types | ruff, mypy (optional) |
| Infra | Docker Compose (postgres, redis, mailhog, api, worker), GitHub Actions CI |
| Frontend (last) | React, TypeScript, React Query, `html5-qrcode` for the scanner page |

### Repo layout

```
sportreg/
  app/
    main.py
    config.py            # env settings, startup safety checks
    db.py                # async engine/session
    deps.py              # auth + role dependencies
    models.py            # SQLAlchemy models
    schemas.py           # Pydantic request/response models
    errors.py            # error codes + exception handlers
    routers/
      me.py events.py categories.py registrations.py teams.py checkin.py organizer.py health.py
    services/
      registration_service.py   # seat claim, cancel, promote
      team_service.py
      checkin_service.py
      idempotency.py
      qr.py                     # sign/verify tokens
      outbox.py                 # enqueue helper
      rate_limit.py
    worker/
      outbox_worker.py
  alembic/
  tests/
    conftest.py
    test_registration.py test_concurrency.py test_idempotency.py
    test_waitlist.py test_teams.py test_checkin.py test_qr.py
  loadtests/locustfile.py
  docker-compose.yml
  .github/workflows/ci.yml
  README.md
  DESIGN.md             # design decisions (write as you build)
  LOADTEST.md           # measured results (fill after M5)
  SPEC.md  CLAUDE.md
```

### Environment variables

```
ENV=dev|prod
AUTH_MODE=dev|clerk
CLERK_JWKS_URL=
CLERK_ISSUER=
DATABASE_URL=postgresql+asyncpg://sportreg:sportreg@localhost:5432/sportreg
TEST_DATABASE_URL=postgresql+asyncpg://sportreg:sportreg@localhost:5432/sportreg_test
REDIS_URL=redis://localhost:6379/0
QR_SECRET=<long random string>
SMTP_HOST=localhost
SMTP_PORT=1025
MAIL_FROM=no-reply@sportreg.local
OUTBOX_POLL_SECONDS=2
OUTBOX_MAX_ATTEMPTS=8
```

---

## 3. Data model (PostgreSQL DDL)

All timestamps are `timestamptz` stored in UTC. The client displays IST.

```sql
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TYPE user_role AS ENUM ('participant', 'volunteer', 'organizer', 'admin');
CREATE TYPE event_status AS ENUM ('draft', 'published', 'closed');
CREATE TYPE participation_type AS ENUM ('individual', 'team');
CREATE TYPE registration_status AS ENUM ('confirmed', 'waitlisted', 'cancelled', 'checked_in');
CREATE TYPE team_status AS ENUM ('forming', 'registered', 'cancelled');
CREATE TYPE outbox_status AS ENUM ('pending', 'sent', 'failed');

CREATE TABLE users (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_id     text NOT NULL UNIQUE,
    email       citext NOT NULL UNIQUE,
    name        text NOT NULL,
    college     text,
    roll_no     text,
    phone       text,
    role        user_role NOT NULL DEFAULT 'participant',
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE events (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug           text NOT NULL UNIQUE,
    name           text NOT NULL,
    description    text,
    venue          text,
    starts_at      timestamptz NOT NULL,
    ends_at        timestamptz NOT NULL,
    reg_opens_at   timestamptz NOT NULL,
    reg_closes_at  timestamptz NOT NULL,
    status         event_status NOT NULL DEFAULT 'draft',
    created_by     uuid NOT NULL REFERENCES users(id),
    created_at     timestamptz NOT NULL DEFAULT now(),
    CHECK (reg_opens_at < reg_closes_at),
    CHECK (reg_closes_at <= ends_at),
    CHECK (starts_at < ends_at)
);

CREATE TABLE categories (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id         uuid NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    name             text NOT NULL,
    sport            text NOT NULL,
    participation    participation_type NOT NULL,
    team_size_min    int,
    team_size_max    int,
    capacity         int NOT NULL CHECK (capacity > 0),
    confirmed_count  int NOT NULL DEFAULT 0,
    waitlist_enabled boolean NOT NULL DEFAULT true,
    UNIQUE (event_id, name),
    CHECK (confirmed_count >= 0 AND confirmed_count <= capacity),
    CHECK (
        (participation = 'individual' AND team_size_min IS NULL AND team_size_max IS NULL)
        OR
        (participation = 'team' AND team_size_min >= 1 AND team_size_max >= team_size_min)
    )
);

CREATE TABLE teams (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    category_id  uuid NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    name         text NOT NULL,
    captain_id   uuid NOT NULL REFERENCES users(id),
    invite_code  text NOT NULL UNIQUE,
    status       team_status NOT NULL DEFAULT 'forming',
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (category_id, name)
);

-- category_id is denormalized so a user can be in at most one team per category.
-- When a team is cancelled, delete its team_members rows so users are freed.
CREATE TABLE team_members (
    team_id      uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    user_id      uuid NOT NULL REFERENCES users(id),
    category_id  uuid NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    joined_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, user_id),
    UNIQUE (category_id, user_id)
);

-- One registration = one occupied "seat" (a participant or a whole team).
-- For team registrations user_id is the captain and team_id is set.
CREATE TABLE registrations (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    category_id   uuid NOT NULL REFERENCES categories(id),
    user_id       uuid NOT NULL REFERENCES users(id),
    team_id       uuid REFERENCES teams(id),
    status        registration_status NOT NULL,
    waitlisted_at timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);

-- No duplicate active registration per user per category; cancelled rows are exempt.
CREATE UNIQUE INDEX uq_active_registration
    ON registrations (category_id, user_id) WHERE status <> 'cancelled';
CREATE INDEX ix_reg_waitlist
    ON registrations (category_id, waitlisted_at, id) WHERE status = 'waitlisted';
CREATE INDEX ix_reg_category_status ON registrations (category_id, status);
CREATE INDEX ix_reg_user ON registrations (user_id);

CREATE TABLE check_ins (
    registration_id uuid PRIMARY KEY REFERENCES registrations(id),
    checked_in_by   uuid NOT NULL REFERENCES users(id),
    checked_in_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE idempotency_keys (
    user_id          uuid NOT NULL REFERENCES users(id),
    key              text NOT NULL,
    method           text NOT NULL,
    path             text NOT NULL,
    request_hash     text NOT NULL,
    response_status  int,
    response_body    jsonb,
    created_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, key)
);

CREATE TABLE outbox (
    id               bigserial PRIMARY KEY,
    event_type       text NOT NULL,
    payload          jsonb NOT NULL,
    status           outbox_status NOT NULL DEFAULT 'pending',
    attempts         int NOT NULL DEFAULT 0,
    next_attempt_at  timestamptz NOT NULL DEFAULT now(),
    last_error       text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    sent_at          timestamptz
);
CREATE INDEX ix_outbox_pending ON outbox (next_attempt_at) WHERE status = 'pending';
```

`confirmed_count` counts registrations in status `confirmed` or `checked_in`.

**Core invariants (write tests for each):**
1. `confirmed_count == count(registrations WHERE status IN ('confirmed','checked_in'))` for every category.
2. `confirmed_count <= capacity`.
3. If a category has any `waitlisted` registration, then `confirmed_count == capacity`.
4. A user has at most one non-cancelled registration per category.
5. A user is in at most one team per category.

---

## 4. Core flows

### 4.1 Register (individual category)

`POST /categories/{id}/registrations` with required header `Idempotency-Key`.

In **one transaction**:
1. Load category + event. Check event `published` and `now()` within `[reg_opens_at, reg_closes_at]`, otherwise `409 registration_closed`. Check `participation = 'individual'`.
2. Idempotency: `INSERT INTO idempotency_keys (...) ON CONFLICT DO NOTHING`.
   - Inserted: continue.
   - Conflict: read the existing row. If `request_hash` differs, return `422 idempotency_key_reuse`. If a stored response exists, return it unchanged.
   - Because the insert happens inside the same transaction as the work, a concurrent duplicate request blocks on the unique index until the first transaction commits, then sees the stored response.
3. Claim a seat atomically:
   ```sql
   UPDATE categories
      SET confirmed_count = confirmed_count + 1
    WHERE id = :category_id AND confirmed_count < capacity
   RETURNING id;
   ```
   - Row returned: insert registration `confirmed`, enqueue outbox `registration_confirmed`.
   - No row, `waitlist_enabled`: insert registration `waitlisted` with `waitlisted_at = now()`, enqueue `registration_waitlisted`. Respond with `waitlist_position`.
   - No row, waitlist disabled: `409 category_full`.
4. Duplicate registration is rejected by `uq_active_registration`. Catch the integrity error and return `409 already_registered`.
5. Store the success response in the idempotency row and commit. Error responses roll the transaction back, so the key is not consumed.

Why the conditional UPDATE: the database decides who gets the last seat. A "read the count, then insert" approach is a race condition. The UPDATE takes a row lock on the category row, so seat claims for one category are serialized. That row is also the contention point under load, which is acceptable at this scale and a good interview talking point.

### 4.2 Cancel and waitlist promotion

`DELETE /registrations/{id}` (owner or organizer). Not allowed for `checked_in` (`409`).

In one transaction:
1. `SELECT ... FROM categories WHERE id = :cid FOR UPDATE` (serializes with seat claims and other cancellations for this category).
2. Mark the registration `cancelled`. For a team registration also mark the team `cancelled` and delete its `team_members` rows.
3. If the cancelled registration was `confirmed`:
   - Find the oldest waitlisted registration: `ORDER BY waitlisted_at, id LIMIT 1`.
   - Found: set it `confirmed` (the seat transfers, `confirmed_count` unchanged) and enqueue `waitlist_promoted`.
   - None: `UPDATE categories SET confirmed_count = confirmed_count - 1`.
4. If the cancelled registration was `waitlisted`: no count change.
5. Enqueue `registration_cancelled` for the cancelled user.

Raising capacity (`PATCH /categories/{id}`) must promote waitlisted registrations to fill the new seats inside the same locked transaction. Lowering capacity below `confirmed_count` is rejected (`409`).

### 4.3 Teams

1. `POST /categories/{id}/teams` creates a team (`forming`), adds the captain as a member, and returns an `invite_code`.
2. `POST /teams/join` with `invite_code` adds the user. It fails if the team is not `forming`, is at `team_size_max`, or the user is already in a team for this category (`409`).
3. `POST /teams/{id}/register` (captain only, `Idempotency-Key` required) checks `team_size_min <= members <= team_size_max`, then runs the same seat-claim logic as 4.1 with `team_id` set. The team becomes `registered`, and its roster is locked.
4. `DELETE /teams/{id}` cancels the team (and its registration, following 4.2).

### 4.4 Outbox and worker

- Every state change enqueues an `outbox` row in the same transaction. Never send email inside a request.
- The worker loop:
  ```sql
  SELECT * FROM outbox
   WHERE status = 'pending' AND next_attempt_at <= now()
   ORDER BY id
   FOR UPDATE SKIP LOCKED
   LIMIT 20;
  ```
  Send each email. On success set `sent`. On failure increment `attempts`, set `last_error`, and set `next_attempt_at = now() + backoff(attempts)`. After `OUTBOX_MAX_ATTEMPTS` set `failed`.
- This is at-least-once delivery. Make email content safe to send twice (include the registration ID).
- Confirmation emails include the signed QR token (see 4.5), rendered as a QR image or a link.

### 4.5 QR tokens and check-in

- Token: `"{registration_id}.{b64url(HMAC_SHA256(QR_SECRET, 'reg:' + registration_id + ':' + category_id))}"`.
- `POST /events/{event_id}/check-in` with `{ "token": "..." }`, roles `volunteer`, `organizer`, `admin`:
  1. Split and verify the signature with a constant-time compare. Failure returns `400 invalid_token`.
  2. Load the registration and its category. The category must belong to `event_id`, otherwise `409 wrong_event`.
  3. Status `confirmed`: set `checked_in`, insert into `check_ins`. Status `checked_in`: return `200` with `already_checked_in: true`. Status `waitlisted` or `cancelled`: `409` with the status.
  4. Idempotent by design: `INSERT INTO check_ins ... ON CONFLICT DO NOTHING`.

---

## 5. API reference

Conventions:
- JSON everywhere. Errors use `{ "error": { "code": "snake_case_code", "message": "human text" } }`.
- IDs are UUIDs. List endpoints use cursor pagination (`?limit=50&cursor=...`).
- `401` unauthenticated, `403` wrong role, `404` not found, `409` state conflict, `422` validation, `429` rate limited (with `Retry-After`).

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/healthz` | public | liveness + DB ping |
| GET | `/me` | any | creates the user row on first call from the auth identity |
| PATCH | `/me` | any | name, college, roll_no, phone |
| POST | `/events` | organizer | create draft event |
| GET | `/events` | public | published events only |
| GET | `/events/{id}` | public | includes categories with seats left |
| PATCH | `/events/{id}` | organizer | edit; `status` transitions draft to published to closed |
| POST | `/events/{id}/categories` | organizer | create category |
| PATCH | `/categories/{id}` | organizer | capacity change triggers promotion (4.2) |
| POST | `/categories/{id}/registrations` | participant | **Idempotency-Key required**, rate limited |
| GET | `/me/registrations` | any | with status and `waitlist_position` |
| DELETE | `/registrations/{id}` | owner/organizer | cancel + promote (4.2) |
| GET | `/registrations/{id}/qr` | owner | returns token |
| POST | `/categories/{id}/teams` | participant | create team |
| POST | `/teams/join` | participant | body `{invite_code}` |
| DELETE | `/teams/{id}/members/me` | member | leave (not captain) |
| POST | `/teams/{id}/register` | captain | **Idempotency-Key required** |
| DELETE | `/teams/{id}` | captain/organizer | cancel team |
| POST | `/events/{id}/check-in` | volunteer/organizer | body `{token}` |
| GET | `/events/{id}/registrations` | organizer | filters: `category_id`, `status`; cursor pagination |
| GET | `/events/{id}/registrations.csv` | organizer | streamed export |
| GET | `/events/{id}/stats` | organizer | per category: capacity, confirmed, waitlisted, checked_in |

### Key request/response shapes

`POST /categories/{id}/registrations`

```
Headers: Authorization: Bearer <jwt>, Idempotency-Key: <uuid>
Body: {}
201 -> { "registration_id": "...", "status": "confirmed" }
201 -> { "registration_id": "...", "status": "waitlisted", "waitlist_position": 7 }
400 missing_idempotency_key | 409 registration_closed | 409 already_registered | 409 category_full | 422 idempotency_key_reuse | 429 rate_limited
```

`POST /events/{id}/check-in`

```
Body: { "token": "<registration_id>.<signature>" }
200 -> { "registration_id": "...", "status": "checked_in", "already_checked_in": false, "participant": { "name": "...", "category": "..." } }
400 invalid_token | 409 wrong_event | 409 not_confirmed
```

`GET /events/{id}/stats`

```
200 -> { "categories": [ { "id": "...", "name": "...", "capacity": 32, "confirmed": 32, "waitlisted": 11, "checked_in": 20 } ] }
```

### Rate limiting (M5)

- `POST` registration endpoints: 10 per minute per user and 60 per minute per IP, via a Redis sliding window.
- Check-in: 120 per minute per volunteer.
- Tests use an in-memory limiter.

---

## 6. Testing plan (what each test must prove)

Use a real Postgres test database, a fresh schema per test session, and truncated tables between tests.

1. **Capacity under concurrency.** 200 distinct users register simultaneously for a category with capacity 50 (`asyncio.gather`). Assert exactly 50 `confirmed`, 150 `waitlisted` (or 150 `409` when the waitlist is disabled), and `confirmed_count == 50`.
2. **Idempotent retry.** The same user and key sent 20 times concurrently produces exactly one registration, and every response is identical.
3. **Key reuse with a different body or path** returns `422 idempotency_key_reuse`.
4. **Duplicate registration** with a fresh key returns `409 already_registered`.
5. **Registration window.** Before open and after close return `409 registration_closed`.
6. **Waitlist order.** Cancel a confirmed seat. The earliest waitlisted user is promoted, and the promotion email is in the outbox.
7. **Concurrent cancellations.** Cancel 10 confirmed seats at once with 10 or more waitlisted. Exactly 10 distinct users are promoted, with no double promotion and `confirmed_count == capacity`.
8. **Invariant check.** After tests 1, 6 and 7, assert all five invariants from section 3.
9. **Capacity increase** promotes the right number of waitlisted users. Capacity decrease below confirmed is rejected.
10. **Teams.** Team size bounds, a user cannot join two teams in one category, the roster is locked after registration, and cancelling a team frees its members.
11. **Outbox atomicity.** Force a failure after the registration insert inside the transaction. Assert neither the registration nor the outbox row exists.
12. **Outbox worker retry.** A failing SMTP stub produces increasing `attempts`, backoff, then `failed`. Success marks `sent`.
13. **QR.** Forged, tampered and wrong-event tokens are rejected. A double scan returns `already_checked_in`. A waitlisted or cancelled token returns `409`.
14. **Role checks.** Participants cannot call organizer or volunteer endpoints.

CI (`.github/workflows/ci.yml`): start Postgres (and Redis) as services, run `alembic upgrade head`, `ruff check`, and `pytest`.

---

## 7. Load testing (after M4)

`loadtests/locustfile.py` scenarios:
- **Browse:** `GET /events`, `GET /events/{id}` (80 percent of traffic).
- **Launch spike:** unique users registering in a category (20 percent), ramping from 0 to 300 users over 30 seconds, then holding.

Record in `LOADTEST.md`: environment (machine specs, Docker on one laptop), request rate, p50/p95/p99 latency, error rate, and the final invariant check. Then do the same with and without Redis caching on `GET /events/{id}` and note the difference. Any resume number must come from this file, with the environment stated.

---

## 8. Milestones with acceptance criteria

**M1: Core registration (do this first)**
- Alembic migrations, models, dev auth, events and categories CRUD, individual registration with the atomic seat claim, cancellation without waitlist.
- Done when tests 1, 4, 5 pass and invariants 1, 2 and 4 hold.

**M2: Idempotency and waitlist**
- Idempotency keys, waitlist, promotion on cancel, capacity changes.
- Done when tests 2, 3, 6, 7, 8, 9 pass.

**M3: Outbox, worker, QR and check-in**
- Outbox enqueue helper, worker with retry, email with QR token, check-in endpoint.
- Done when tests 11, 12, 13 pass and a MailHog email shows a working QR.

**M4: Teams and organizer tools**
- Team flow, registrations list, CSV export, stats, role checks.
- Done when tests 10 and 14 pass.

**M5: Hardening and proof**
- Redis rate limiting and caching, Docker Compose for everything, CI, load test, `LOADTEST.md`, `DESIGN.md`, README with architecture diagram, deploy.
- Done when the load test is recorded and CI is green on the main branch.

**M6: Frontend (thin)**
- Event list, register button with a fresh `Idempotency-Key` per attempt, my registrations with QR, organizer dashboard, volunteer scanner page.

**Stretch (only after M5):** single-elimination bracket generation, seeding, Elo-style ranking, a leaderboard.

If time runs short, cut M6 and the stretch, never M1 to M3.

---

## 9. Interview talking points (be able to answer these without notes)

1. **Why a conditional UPDATE and not read-then-insert?** The check and the claim happen atomically in the database. Two concurrent requests cannot both see "one seat left".
2. **What is the bottleneck?** The per-category row lock. It is fine at this scale. Alternatives are sharding seats into buckets or a Redis counter, with the trade-offs in consistency and complexity.
3. **How does idempotency work?** The key row is inserted in the same transaction as the work. A concurrent duplicate blocks on the unique index and then returns the stored response. Request-hash mismatch is rejected.
4. **Why an outbox?** It avoids dual writes: a seat is never confirmed without its email being queued, and no email goes out for a rolled-back seat. Delivery is at-least-once, so emails must tolerate duplicates.
5. **How is the waitlist race-safe?** Promotion runs under the category row lock, and invariant 3 (waitlist non-empty implies full) is tested.
6. **How are QR tokens secured?** HMAC with a server secret and constant-time verification. Tokens carry no PII, and the check-in is idempotent.
7. **What would you change at 100x scale?** Read replicas and caching for browse traffic, a queue for notifications, and splitting the seat counter if one category becomes the hotspot.
8. **Hardest bug you hit?** Fill this in from real bugs you hit while building. Keep a short bug log in `DESIGN.md` as you go, since this is the question that gets asked.

---

## 10. Resume bullet templates (fill with measured numbers only)

- Built a capacity-safe event registration backend (FastAPI, PostgreSQL) using atomic conditional updates and per-category locking; a concurrency test of `[N]` simultaneous requests for `[M]` seats produced exactly `[M]` confirmed registrations.
- Implemented idempotent registration endpoints and a transactional outbox with a retrying worker, so retries never double-register and no seat is confirmed without a queued email.
- Designed an HMAC-signed QR check-in flow and a race-safe waitlist with automatic promotion; load-tested at `[X]` req/s with p95 `[Y]` ms (Docker on a single laptop, see `LOADTEST.md`).
- Backstory line (only if true): "Built after managing registrations for `[the real events you ran]`." Mention real usage only if the system was used for an actual event, with the real number.

---

## 11. Things NOT to do

- Do not use SQLite for tests.
- Do not read a count in Python and then insert.
- Do not send email inside the request handler.
- Do not store raw registration IDs in QR codes without a signature.
- Do not add Celery, Kafka, Kubernetes or an AI feature.
- Do not claim users, traffic, or performance numbers you did not measure.
- Do not leave `AUTH_MODE=dev` reachable in production.

---

## 12. CLAUDE.md (paste into the repo root)

````
# Project: EntriX

Read SPEC.md first. It is the source of truth for schema, flows, API and milestones.

## Rules
- Work milestone by milestone (M1, M2, ...). Do not start a milestone until the previous one's acceptance criteria pass.
- Write the tests listed in SPEC.md section 6 for each milestone before or alongside the code. Tests run against real PostgreSQL, never SQLite.
- Seat claims must use the atomic conditional UPDATE in SPEC.md 4.1. Never read-then-write capacity in Python.
- Cancellation and capacity changes lock the category row (SELECT ... FOR UPDATE) before promoting from the waitlist.
- All state changes that need email enqueue an outbox row in the same transaction. Never send email in a request handler.
- Idempotency rows are inserted in the same transaction as the work. Business errors roll back and do not store a response.
- Keep the five invariants from SPEC.md section 3 true and covered by tests.
- Use SQLAlchemy 2.0 async style, Alembic migrations for every schema change (no create_all in app code), Pydantic v2 schemas, and typed code.
- Keep changes small and runnable at every step. After each milestone, run ruff and pytest and report results.
- Do not add dependencies or features outside SPEC.md without asking.
- Do not fabricate metrics. Performance numbers come only from loadtests/ output recorded in LOADTEST.md.

## Commands
- docker compose up -d postgres redis mailhog
- alembic upgrade head
- pytest -x -q
- ruff check .
- uvicorn app.main:app --reload
- python -m app.worker.outbox_worker
````

---

## 13. First prompt for Claude Code

Paste this after adding `SPEC.md` and `CLAUDE.md` to an empty repo:

> Read SPEC.md and CLAUDE.md. Implement Milestone M1 only. Start by proposing the exact file list you'll create and any decisions that deviate from the spec, then wait for my approval before writing code. After approval: set up the project skeleton (FastAPI, SQLAlchemy 2.0 async, Alembic, docker-compose for Postgres), write the migration from the DDL in section 3, implement dev auth, events and categories CRUD, the individual registration flow with the atomic seat claim, and cancellation. Write tests 1, 4 and 5 from section 6 plus the invariant checks, run them, and report the results.
