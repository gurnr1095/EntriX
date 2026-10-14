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
