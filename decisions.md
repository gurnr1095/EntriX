# Decisions log (plain-language, for interview prep)

Each entry says what we chose, why, and the likely interview question it answers.

## M1: Core registration

### 1. A full category is decided by one SQL statement
`UPDATE categories SET confirmed_count = confirmed_count + 1 WHERE id = :id AND confirmed_count < capacity RETURNING id`.
If a row comes back, the user got a seat. If not, the category was full.
We never read the count in Python and then write, because two requests could both read "49 of 50" and both take the last seat.
The UPDATE locks the category row, so seat claims for one category happen one at a time and the database is the referee.
*Question: why not read-then-insert?* The check and the claim must be one atomic step.
*Question: what is the bottleneck?* That same row lock. It is fine at campus scale.

### 2. Cancellation locks the category first
`SELECT ... FOR UPDATE` on the category row, then re-read the registration under the lock.
Re-reading matters: if five cancel requests for the same registration arrive together, the first one wins and the other four see "already cancelled" (409), so the seat is only released once.
The lock is also what M2 will rely on when promoting from the waitlist.

### 3. Duplicate check happens before the seat claim, but the index is the real guard
A cheap lookup lets a duplicate get `already_registered` even when the category is full (better than a confusing `category_full`).
The partial unique index `uq_active_registration` is what truly guarantees one active registration per user per category, including under races.
Any failure rolls the whole transaction back, so a failed duplicate never consumes a seat.

### 4. Everything is one transaction, including the outbox row
The registration, the seat counter and the `outbox` row commit together or not at all.
So a confirmed seat always has a queued email, and a rolled-back seat never has one.
M1 only queues rows; the worker and email arrive in M3.

### 5. Waitlist and idempotency are deliberately not in M1
The `Idempotency-Key` header is required (400 if missing) but not stored yet; the table exists in the migration.
A full category returns `409 category_full` for now. Waitlist and promotion are M2.

### 6. Dev auth
`X-Dev-User: <email>` finds or creates the user. `X-Dev-Role` sets the role only when the user is first created, and only in dev mode, so tests can make organizers.
The app refuses to start with `AUTH_MODE=dev` when `ENV=prod` (tested).
Clerk mode returns 501 until it is built.
The user lookup uses its own short session so the request's transaction starts clean.

### 7. Migrations, not create_all
The migration runs the DDL from SPEC section 3 as written, one statement per call (asyncpg cannot run several commands in one call).
Tests drop the schema, run `alembic upgrade head` once per session, and truncate tables between tests. Tests therefore exercise the real migration.

### 8. Tests use real PostgreSQL
Concurrency behaviour is the point of the project, and SQLite would hide it.
Test 1 fires 200 simultaneous requests at 50 seats and asserts exactly 50 confirmed, 150 `category_full`, the counter equal to 50, and 50 queued emails.
`tests/invariants.py` checks all five invariants from SPEC section 3 and is called at the end of every concurrency test.

### 9. Other small choices
- Registration window is checked against the database clock (`now()`), not Python's.
- Any authenticated user may register (not only the `participant` role) so organizers can test their own events.
- Event status moves one step at a time: draft, published, closed. Drafts are hidden from public endpoints.
- Lowering capacity below `confirmed_count` is rejected (409). Raising works; promotion is M2.
- `GET /events` uses keyset (cursor) pagination on `(starts_at, id)`, not offsets.
- The test engine pool is 20 + 20 overflow so 200 concurrent requests queue for connections instead of failing.

### 10. Local setup note: Postgres on port 5433
This machine already runs a native PostgreSQL on port 5432, so the Docker container is published on host port **5433**.
Defaults in `config.py`, `.env.example` and the tests use 5433. The spec's examples use 5432; change both if your machine has no clash.

## M2: Idempotency and waitlist

### 11. How idempotency works
The `Idempotency-Key` row is inserted in the same transaction as the registration, with `INSERT ... ON CONFLICT DO NOTHING`.
If 20 identical requests arrive together, 19 of them block on the unique index until the first transaction finishes.
If it committed, they read its stored response and return it. If it rolled back (a business error), one of them gets to do the work. Either way, one registration.
The stored response is the success answer only. Errors roll back, so a failed request never "uses up" a key (tested: fix the problem, retry with the same key, it works).
*Question: what if the same key is reused for something else?* The request hash covers method, path and body, so a different category, path or body gives `422 idempotency_key_reuse`.

### 12. Idempotency check runs before validation (deviation from SPEC 4.1 order)
The spec checks the registration window first. We look up the key first instead.
Reason: a retry after the window closes (or the category fills) should replay the original success, not turn into `registration_closed`. Retry-safety is the whole point of the key.

### 13. Replays are byte-identical
Postgres `jsonb` does not keep key order, so a replay came back with the same fields in a different order. Test 2 caught this.
Fix: every registration response is serialized with sorted keys, so fresh responses and replays match exactly.
*Bug-log entry for "hardest bug you hit".*

### 14. The waitlist insert takes the category lock (extra over the spec)
A failed conditional UPDATE locks nothing. Without more care this can happen: user A's claim fails (full), a cancellation commits (seat free, nobody waitlisted yet), then A is inserted as waitlisted. Now a seat is free while someone waits, which breaks invariant 3.
Fix: when the claim fails, take `SELECT ... FOR UPDATE` on the category, try the claim once more, and only then insert the waitlisted row while still holding the lock.
Only the full path pays for the lock; normal registrations stay lock-free.
The same lock makes waitlist order strictly serialized, so positions are exactly 1..N with no gaps or duplicates (tested).

### 15. Fair order
`waitlisted_at` uses `clock_timestamp()`, not `now()`. In Postgres `now()` is the time the transaction started, so it would not reflect arrival order. Ties break on `id`.
Position = how many waitlisted rows sort at or before yours.

### 16. Promotion
Cancelling a confirmed seat promotes the oldest waitlisted registration under the category lock. The seat transfers, so `confirmed_count` does not change; a `waitlist_promoted` outbox row is queued in the same transaction.
If nobody is waiting, the count goes down by one.
Cancelling a waitlisted registration changes no count and promotes nobody.
Raising capacity promotes `min(waitlisted, new seats)` people in order, in the same locked transaction. Lowering below the confirmed count is rejected (409).
Turning `waitlist_enabled` off does not remove people already waiting; it only affects new registrations.

### 17. `GET /me/registrations`
Added so waitlisted users can see their position (it is in the spec's API table). Cursor pagination, newest first. The position is computed in SQL with a correlated subquery, not per row in Python.

### 18. Known gap
Idempotency rows are never deleted. A cleanup job (for example, delete rows older than 24 hours) is a later hardening item.

## M3: Outbox worker, QR tokens and check-in

### 19. Why an outbox at all
The request handler never talks to SMTP. It writes an `outbox` row in the same transaction as the registration.
So: a confirmed seat always has its email queued, and a rolled-back seat never has one (test 11 forces a crash after the insert and checks that the registration, the seat count, the outbox row and the idempotency row all vanish; the same request then succeeds).
Without this you would have a "dual write": save to the DB, then call the mail server. If the second step fails you have a seat with no email; if you email first and the commit fails, you email about a seat that does not exist.

### 20. The worker
Loop: `SELECT ... FOR UPDATE SKIP LOCKED LIMIT 20`, send each, mark `sent`; on failure add 1 to `attempts`, store `last_error`, push `next_attempt_at` out; after `OUTBOX_MAX_ATTEMPTS` (8) mark `failed`.
`SKIP LOCKED` means two workers never grab the same row (tested with three workers draining 30 rows: each sent exactly once).
Backoff is 5s, 10s, 20s ... capped at 15 minutes. The spec left this open; doubling is the usual choice, and the cap stops it waiting for hours.
Delivery is **at-least-once**: if the worker crashes after sending but before committing, the row is retried and the email goes out twice. So each email names the registration ID and carries an `X-Entrix-Outbox-Id` header, and nothing in it is harmful if repeated.
*Question: why not exactly-once?* Not possible across two systems (DB and mail server) without something like two-phase commit; at-least-once plus safe-to-repeat messages is the practical answer.

### 21. Emails look things up at send time
Outbox payloads hold only IDs. The worker loads the user, category and event when it sends, so there are no copied email addresses sitting in the outbox and the content is current.
If a "confirmed" or "promoted" row is processed after that registration was cancelled, it is marked sent without emailing a QR for a dead seat (tested).
An unknown event type fails and retries rather than silently disappearing.

### 22. QR token
`<registration_id>.<base64url(HMAC-SHA256(QR_SECRET, "reg:" + registration_id + ":" + category_id))>`.
No personal data inside, so a photographed QR leaks nothing but an ID. Verification recomputes the HMAC from the registration's real category and compares with `hmac.compare_digest` (constant time, so response timing does not leak how many characters matched).
An unknown registration ID returns the same `invalid_token` as a bad signature, so the endpoint cannot be used to probe which IDs exist.
In prod the app refuses to start with the placeholder `QR_SECRET`.

### 23. Check-in is idempotent by design
The registration row is locked (`FOR UPDATE`), so ten simultaneous scans of one QR give exactly one real check-in and nine `already_checked_in: true` answers (tested). `check_ins` also uses `ON CONFLICT DO NOTHING` as a second guard.
`confirmed_count` does not change on check-in, because it already counts `checked_in` rows.
Waitlisted or cancelled tokens get `409 not_confirmed`; a token for another event gets `409 wrong_event`. The signature is checked first, so a forged token is always a 400 whatever event it names.
A checked-in registration cannot be cancelled (409), which keeps the invariants simple.

### 24. New dependency: segno
Approved for drawing the QR image (pure Python, no extra dependencies, writes PNGs without Pillow). Everything else uses the standard library: `smtplib` (run through `asyncio.to_thread`) and `email`.

### 25. Bug log: real problems found while verifying M3
- **Inline image did not show in MailHog.** My first layout nested the image inside the HTML part. MailHog's UI only looks for `Content-ID` on top-level parts (it has a FIXME saying so), so the image showed as broken. The standard layout is `multipart/related[ alternative[text, html], image ]`, so I switched to it. Real mail clients handle it too.
- **Python's email library cannot turn an `alternative` into a `related` message** ("Cannot convert alternative to related"), so the first fix attempt failed at send time. The outbox did its job here: the row stayed pending, `attempts` went up, the backoff applied, and nothing was lost. After the fix the rows were sent.
- **"Is the QR in the email really the token?"** An early comparison said no. The cause was my check, not the email: the plain-text part is quoted-printable, which soft-wraps long lines, so my copy of the token was cut short. After decoding the part, the QR in the email and the token match module for module, and scanning that token checks the person in.

### 26. Running it locally
```
docker compose up -d postgres mailhog
alembic upgrade head
uvicorn app.main:app --reload
python -m app.worker.outbox_worker
```
MailHog's inbox is at http://localhost:8025.

## M4: Teams and organizer tools

### 27. A team is one seat
A team registers as a single registration owned by the captain (`user_id` = captain, `team_id` set), so the seat counter, waitlist, promotion, idempotency and cancellation code is shared with individuals (`place_registration`). Capacity counts teams, not people.
Confirmation and promotion emails go to the captain only; members are not emailed in M4.

### 28. Locking order: category, then team (and why it matters)
Cancelling or registering a team locks the category row first, then the team row. Joining a team only ever locks the team row.
A rule like "always take locks in the same order" is what prevents deadlocks: two transactions can only deadlock if one holds A and wants B while the other holds B and wants A.
The roster is locked by the same mechanism: a join that was waiting on the team row re-reads it after the registration commits, sees `registered`, and is refused with `roster_locked`.
`UNIQUE (category_id, user_id)` on `team_members` is the backstop for invariant 5, so even a missed lock could not put one person in two teams.

### 29. Lifecycle rules
- `forming`: people can join and leave. `registered`: roster locked (join and leave both refused), even while waitlisted. `cancelled`: members freed.
- The captain cannot leave; they cancel the team instead.
- Creating or joining a team needs a published event with the registration window open (my call, the spec is silent). Leaving and cancelling are always allowed.
- Cancelling a team, or cancelling its registration directly, does the same thing: the registration is cancelled (seat transferred to the next waitlisted registration, or released), the team is marked cancelled, and its `team_members` rows are deleted.
- Team size is checked at registration time: `team_size_min <= members <= team_size_max`.
- Invite codes: 8 characters from an alphabet without 0/O/1/I, from `secrets` (not `random`), case-insensitive on join.
- `GET /teams/{id}` (approved addition): members and organizers only; the invite code is shown to the captain and organizers only.

### 30. Organizer tools
- Registration list: filters `category_id` and `status`, cursor pagination on `(created_at, id)`. Organizer and admin only, because it contains personal data.
- CSV: streamed from a server-side cursor in chunks of 500, so memory stays flat for large events (tested with 1,500 rows). It uses its own database session because the request's session is closed before the body finishes streaming.
- CSV formula injection: a cell starting with `=`, `+`, `-` or `@` can run as a formula when opened in Excel or Sheets (a name like `=HYPERLINK(...)`), so such cells get a leading `'`. The JSON list is left untouched, since it is data and not a spreadsheet.
- Stats: one grouped query, not one per category. `confirmed` is the seat counter (confirmed plus checked in), matching the spec's example; `checked_in` is the subset who arrived.

### 31. Role checks
`tests/test_roles.py` is a table of every endpoint against five identities (anonymous, participant, volunteer, organizer, admin): anonymous gets 401, wrong role gets 403, allowed roles never get 401 or 403.
I checked that the table can fail by weakening one endpoint's check on purpose: exactly the two expected cases failed. Then I restored it.
`X-Dev-Role` only applies when a user is first created; a test confirms it cannot promote an existing user.

### 32. Bug log: the deadlock found by the join-vs-register race test
`test_joins_racing_a_registration_leave_a_consistent_roster` failed with `deadlock detected`, in the exact situation the lock ordering was meant to prevent.
**Cause:** inserting a `team_members` row makes Postgres take a `FOR KEY SHARE` lock on the referenced `categories` row, to make sure the category cannot be deleted mid-insert. The category lock I used was a full `FOR UPDATE`, which conflicts with that. So a join held the team and waited on the category, while the registration held the category and waited on the team.
**Fix:** use `FOR NO KEY UPDATE` for the category and team locks. It still conflicts with itself and with `UPDATE`, so seat claims, cancellations and capacity changes are still serialized; it just does not conflict with foreign-key checks.
The race test now passes 15 repeated runs. This is a strong answer to "hardest bug you hit": a lock-ordering argument that looked right on paper but missed a lock Postgres takes implicitly.

### 33. Lint setting
Tests are exempt from the line-length rule (long SQL strings and assertions read better unwrapped). App code is still held to 100 columns.

## M5: Hardening and proof

### 34. Rate limiting
Redis sorted set per key (per user, per IP), one Lua script per check: drop old hits, count, then refuse or record. A script is atomic in Redis, so two API processes cannot both see "9 of 10" and both let a request through (tested with 100 racing hits through two limiter objects: exactly 10 allowed). The script uses the Redis server's clock so every API instance agrees on "now".
Limits are the spec's (10/min per user and 60/min per IP on registration, 120/min per volunteer on check-in), all environment variables. Over the limit gives `429` with `Retry-After`.
- **Fails open.** If Redis is unreachable the request goes through and an error is logged. A cache outage must not stop people registering.
- **Refused requests still count**, so hammering a refused endpoint does not pay off.
- **Idempotent replays count too**: a retry is still a request.
- Tests use an in-memory limiter (as the spec says); the Redis version is tested separately against a real Redis.

### 35. Which client IP?
Behind a reverse proxy the socket address is the proxy's, so every visitor would share one 60/min limit. `TRUSTED_PROXY_HOPS=N` takes the Nth entry **from the right** of `X-Forwarded-For`: the left side is written by the client and can be forged (tested: rotating a fake left entry does not escape the limit). `0` ignores the header.
I could not verify how many proxies Render puts in front of the app, so the number is a setting you confirm after deploying (the app logs the resolved IP and the raw header whenever it rate limits, and warns at start-up in production if the value is 0).

### 36. Caching
`GET /events/{id}` and `GET /events` are cached for 3 seconds in Redis. Only successful reads are cached (a 404 never is, so publishing an event shows up at once). Organizer edits to an event or its categories delete the detail entry; the list refreshes by TTL only.
**Trade-off:** `seats_left` on a browse page can lag by up to 3 seconds. Registration never reads the cache, so this cannot cause overbooking (tested: a stale page says one seat is left, the booking path still answers `category_full`).
Responses carry `X-Cache: HIT|MISS`, and a test counts SQL statements to prove a hit sends none. `CACHE_ENABLED=false` switches it off, which the load test uses for the with/without comparison.

### 37. Clerk sign-in
RS256 only (the token's own `alg` header is never trusted), issuer checked, `exp`/`iat`/`sub` required, 10 seconds of clock leeway. Keys come from Clerk's JWKS and are cached by the library; the blocking fetch runs in a thread.
Roles are never read from the token. A new user is a `participant`; an admin promotes people with SQL (DEPLOY.md). Dev headers are ignored entirely in Clerk mode. Clerk being unreachable is `503`, not `401`, so clients do not think a valid session is bad.
Tests use a locally generated RSA key and a JWKS stub, including the classic attacks (HS256 signed with the public key, `alg: none`, wrong issuer, expired, wrong signer). I weakened the issuer check on purpose to confirm the test notices.
Clerk's default token has no email, so the project needs a custom claim (DEPLOY.md); without it the API explains exactly what to fix.

### 38. Production wiring
- `Dockerfile`: slim Python image, non-root user, installs only runtime dependencies. `$PORT` is honoured (Render sets it) and `WEB_CONCURRENCY` sets uvicorn workers.
- `docker-compose.yml`: postgres, redis, mailhog, a one-shot `migrate` job, the api and the worker, with healthchecks; knobs (cache, limits, pool, workers) are overridable from the shell. The old "just the backing services" command still works.
- `render.yaml`: database, Key Value store, web service (runs `alembic upgrade head` before each deploy) and worker. `QR_SECRET` must be identical on the API and the worker, so it is prompted for on both (I could not confirm that Render can share one generated value across services).
- `DATABASE_URL`: hosting platforms hand out `postgres://` URLs; the app converts them to the async driver.
- Real email needs authentication and TLS: `SMTP_USER`, `SMTP_PASSWORD` and `SMTP_STARTTLS` (port 587). Credentials are only sent after TLS is on (tested).
- The worker has its own start-up check so it cannot run in production with the placeholder QR secret.
- Connection pools are per process: processes x (pool + overflow) must stay under Postgres's 100 connections, so pool size is a setting now.

### 39. CI
Postgres 16 and Redis 7 as services; `alembic upgrade head` on an empty database, `ruff check`, `pytest`; Python 3.12 and 3.13. The Redis tests skip locally when Redis is down but **fail** in CI (`REQUIRE_REDIS=1`), so they cannot silently stop running there. I could only run 3.13 locally, so 3.12 is untested until the first CI run.

### 40. Load test method
Every number in `LOADTEST.md` is generated by `loadtests/summarize.py` from Locust's CSV files; none is typed. The runner resets the database and Redis, restarts the API in a known configuration, seeds data, runs Locust, then checks the five invariants against the database.
The first trial caught a real flaw in the test itself (browse traffic started before the seed finished and silently produced exceptions instead of requests), which is why seeding is now a separate step. Limits are in the file itself: one laptop running everything including the load generator, dev auth, one run per configuration.
