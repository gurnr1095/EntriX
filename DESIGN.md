# Design

Why EntriX is built the way it is, written for someone who has to defend the choices. The
per-milestone log of what was decided and when is [decisions.md](decisions.md); this is the
condensed reasoning, plus the bugs that taught something.

## The core problem

Hundreds of students hit "register" within seconds, for a few dozen seats. Three things must
hold no matter how requests interleave: **never overbook**, **never double-register**, and
**never lose or invent an email**. Everything below serves one of those.

The five invariants (tested after every concurrency test, and again after the load test):

1. `confirmed_count` equals the number of `confirmed` plus `checked_in` registrations.
2. `confirmed_count <= capacity`.
3. A category with anyone waitlisted is full.
4. A user has at most one non-cancelled registration per category.
5. A user is in at most one team per category.

## Decisions and the reasoning

### Let the database decide who gets the last seat
`UPDATE categories SET confirmed_count = confirmed_count + 1 WHERE id = ? AND confirmed_count < capacity RETURNING id`.
Reading the count in Python and then inserting is a race: two requests both read "49 of 50" and
both take seat 50. One conditional UPDATE makes the check and the claim a single atomic step,
and Postgres' row lock serializes claims for that category.

*Cost:* that one row is the contention point for a hot category. That is acceptable at this
scale. At 100x, the options are sharding a category's seats into buckets or a Redis counter,
trading simplicity and exact consistency for throughput.

### Cancellation, capacity changes and waitlist inserts take the category lock
Anything that moves a seat or promotes from the waitlist runs under
`SELECT ... FOR NO KEY UPDATE` on the category row, so promotion cannot interleave with a claim.
Promotion takes the *oldest* waitlisted registration (`ORDER BY waitlisted_at, id`) and transfers
the seat, so `confirmed_count` does not change.

The less obvious part: a **failed** conditional UPDATE locks nothing. Without more care, a user's
claim fails (full), a cancellation commits (a seat frees, nobody is waiting yet), and then the user
is inserted as waitlisted: a free seat next to a waitlisted person, which breaks invariant 3. So a
failed claim takes the category lock, retries the claim once, and only then inserts the waitlisted
row while still holding the lock. Only the full path pays for the lock.

### `FOR NO KEY UPDATE`, not `FOR UPDATE` (a bug, see below)
Inserting a row that references the category takes a `FOR KEY SHARE` lock on it. A plain
`FOR UPDATE` conflicts with that and caused a deadlock. `FOR NO KEY UPDATE` still excludes other
seat claims (it conflicts with itself and with `UPDATE`) but not foreign-key checks.

### Idempotency lives in the same transaction as the work
The `Idempotency-Key` row is inserted first, with `ON CONFLICT DO NOTHING`. A concurrent duplicate
blocks on the unique index; when the first transaction commits, the duplicate reads the stored
response and returns it byte for byte. If the first one rolls back (a business error), the
duplicate gets to run. Reusing a key for a different request (hash of method, path and body) is a
`422`. Errors roll back, so a rejected request does not use up its key.

The key is checked *before* validation, not after: a retry after the registration window closes
should replay the original success, not become `registration_closed`.

### A transactional outbox instead of sending email in the request
Saving the seat and calling the mail server are two systems; one can succeed while the other
fails. Writing an `outbox` row in the same transaction removes the problem: either both the seat
and its email-to-send exist, or neither does. A worker polls with `FOR UPDATE SKIP LOCKED`
(several workers can run safely), retries with exponential backoff, and marks a row `failed`
after 8 attempts. Delivery is **at-least-once**, so emails carry the registration ID and are
harmless to receive twice. Exactly-once across a database and a mail server is not achievable
without something like two-phase commit.

### QR tokens
`<registration_id>.<HMAC-SHA256 over registration and category>`: no personal data in it,
verified with a constant-time comparison. Check-in locks the registration row, so ten simultaneous
scans of one code produce one check-in and nine `already_checked_in` answers. An unknown ID and a
bad signature give the same answer, so the endpoint cannot be used to discover registration IDs.

### Teams reuse the individual path
A team is one registration owned by the captain, so seat claiming, waitlisting, promotion,
idempotency and cancellation are the same code (`place_registration`). Lock order is always
**category, then team**; joining a team only ever locks the team row. Rosters lock when the team
registers (a join that was waiting on the team row re-reads it and is refused), and
`UNIQUE (category_id, user_id)` on `team_members` backs invariant 5 even if a lock were missed.

### Caching and rate limiting trade a little freshness for load
`GET /events/{id}` is cached for 3 seconds, so `seats_left` on a browse page can lag by up to
that. That cannot cause overbooking, because registration never reads the cache. Organizer edits
delete the cached entry. Rate limits use a Redis sorted-set sliding window inside one Lua script,
so two API processes cannot both see "9 of 10". If Redis is down, both fail open: a broken cache
must not stop people registering.

### Authentication
Clerk RS256 tokens are verified against Clerk's JWKS with the algorithm pinned to RS256 (the token's
own `alg` header is never trusted) and the issuer checked. Roles are **never** read from the token:
a new user is a participant and an admin promotes people in the database, so nobody can claim a
role. Dev-mode headers are ignored entirely in Clerk mode, and the app will not start with dev auth
in production.

## Bug log

These are real; each was found by a test or a check, not by luck.

1. **Replays differed from the original response.** A replayed idempotent request returned the same
   fields in a different order, because Postgres `jsonb` does not keep key order. Found by the
   "20 concurrent retries give identical responses" test. Fix: serialize every registration response
   with sorted keys, so fresh and replayed responses are byte-identical.

2. **Waitlist insert could leave a free seat beside a waiting user.** Found by reasoning about the
   failed-UPDATE case before writing the code, then locked in with a churn test (registrations racing
   cancellations while asserting invariant 3). Fix: take the category lock and retry the claim before
   a waitlist insert.

3. **Deadlock between a team join and a team registration.** The lock-ordering argument looked
   right on paper but missed a lock Postgres takes implicitly: the foreign-key check on `team_members`
   inserts takes `FOR KEY SHARE` on the category row, which a full `FOR UPDATE` blocks. A join held
   the team and waited for the category; the registration held the category and waited for the team.
   Found by a test that races ten joins against a registration. Fix: `FOR NO KEY UPDATE` for the
   category and team locks. The race test then passed 15 repeated runs.

4. **The inline QR image did not show in MailHog.** The image was nested inside the HTML part, and
   MailHog only looks for `Content-ID` in top-level parts. The standard layout is
   `multipart/related[ alternative[text, html], image ]`. Python's email library cannot turn an
   `alternative` into a `related` message ("Cannot convert alternative to related"), so the
   message is built explicitly. While the broken version was live, the outbox retried and backed off
   exactly as designed and nothing was lost.

5. **"The QR in the email does not match the token" (a false alarm worth remembering).** A byte
   comparison of the QR failed. The cause was the check, not the email: the plain-text part is
   quoted-printable, which soft-wraps long lines, so the token I copied out was truncated. Decoding the
   part properly showed zero differing QR modules, and scanning it checked the person in.

6. **The load test measured nothing for browse traffic.** The first trial showed zero event-detail
   requests and 39 `Cannot choose from an empty sequence` exceptions in Locust's exceptions file:
   Locust started spawning users while the seed step was still creating events. Fix: seed in a
   separate step and only then start Locust.

7. **Two tests that passed on the first run were checked for teeth.** The role matrix and the Clerk
   issuer check were each deliberately weakened (one endpoint's role check removed; the issuer
   check removed) to confirm the tests fail; both did, and the code was restored.

8. **A crash after the database went idle (found on the live deployment).** `GET /me` worked,
   then later returned a plain-text 500. Neon suspends its compute after 5 idle minutes and closes
   every connection, but the API process (kept awake by Render and by pings that deliberately do not
   touch the database) still held those connections in its pool; the first request afterwards
   picked up a dead one: `asyncpg InterfaceError: connection is closed`. Reproduced first by
   having Postgres terminate every other session, then fixed with `pool_pre_ping=True` (the pool
   tests a connection before use and replaces a dead one). Lesson: a keep-alive that avoids the
   database guarantees every pooled connection may be stale exactly when real traffic arrives.

9. **Neon's connection string did not work as copied.** It carries `sslmode=require` and
   `channel_binding=require`; asyncpg rejects `sslmode` outright (`TypeError: unexpected keyword
   argument`, reproduced) and does not support `channel_binding`. Fixed by normalising the URL, and
   checked against the real Neon server by running the migration from a laptop.

10. **A test script that did nothing useful the first time.** The email-deliverability script,
    run without settings, silently fell back to the local MailHog defaults and the placeholder
    addresses from the docs, and reported "sent". It now refuses both and says why, and the test suite
    ignores a developer's `.env` so a real key there cannot change test results.

11. **One setting turned every email into a failure on Render only.** `MAIL_FROM` in Render's dashboard
    was `EntriX grkr1095@gmail.com`: the `<angle brackets>` of `Name <address>` were lost, so Brevo got no
    valid sender and rejected every email (`valid sender email required`); each row used its eight attempts.
    My first guess (stray quotes) was wrong; the start-up validation added in response printed the real
    value. Fixes: refuse to start on an unusable sender, treat "sender invalid" as configuration (retry
    later, keep the attempts), and let `MAIL_FROM` be a plain address with the name in `MAIL_FROM_NAME`.

## What would change at 100x
- Browse traffic: read replicas, and the cache in front of them (already in place at small scale).
- Hot category: split the seat counter into buckets, or hand out seats from Redis and reconcile.
- Notifications: a real queue instead of polling a table.
- Rate limiting at the edge (CDN or proxy) rather than in the application.
