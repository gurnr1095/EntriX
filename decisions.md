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
