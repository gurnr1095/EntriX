# Deploying EntriX on Render

`render.yaml` defines four things: a Postgres database, a Redis-compatible Key Value store, the
API (web service) and the outbox worker (background worker). Both services build from the
`Dockerfile`. This guide is what to do around it.

> Not tested end to end: I could not deploy to your Render account, so this has been checked
> against Render's Blueprint reference and by running the same Docker image locally with
> Docker Compose, but the first real deploy may need small adjustments. Plans (and what is
> free) are chosen in Render's dashboard, since they change over time.

## 1. Before you deploy

### Clerk (sign-in)
1. Create a Clerk application and enable the sign-in methods you want.
2. **Add email and name to the session token.** Clerk's default token has neither, and the API
   needs the email. In the Clerk dashboard open *Sessions* and *Customize session token*, and
   add these claims:
   ```json
   { "email": "{{user.primary_email_address}}", "name": "{{user.full_name}}" }
   ```
   Without the `email` claim the API answers `401 missing_email_claim`. The error says what to fix.
3. Note two values: your **issuer** (your Clerk Frontend API URL, `https://...`) and the
   **JWKS URL** (`<issuer>/.well-known/jwks.json`). They become `CLERK_ISSUER` and `CLERK_JWKS_URL`.

### Email (SMTP)
The worker sends confirmation emails with QR codes. Use any SMTP provider (Brevo, Mailgun,
Amazon SES, ...) on port 587 with STARTTLS. You need the host, username, password and a
**verified sender address** for `MAIL_FROM`.

### A secret for QR codes
```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```
You will paste this same value twice (API and worker). Never reuse it elsewhere or commit it.
If it changes, QR codes already emailed stop verifying.

## 2. Create the Blueprint

1. Push the repository to GitHub.
2. In Render: *New*, then *Blueprint*, pick the repository. Render reads `render.yaml`.
3. Render asks for the values marked `sync: false`:

   | Variable | Where | Value |
   |---|---|---|
   | `QR_SECRET` | API **and** worker | the secret above, identical in both |
   | `CLERK_ISSUER`, `CLERK_JWKS_URL` | API | from Clerk |
   | `TRUSTED_PROXY_HOPS` | API | `1` to start, then check (section 4) |
   | `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_FROM` | worker | from your SMTP provider |

4. Choose plans in the dashboard. Whatever you pick for the database, remember a free database
   or Redis may expire or be limited.
5. On the first deploy the API runs `alembic upgrade head` (the `preDeployCommand`) before
   starting, so the schema is created automatically.

The API will refuse to start if `AUTH_MODE=dev` with `ENV=prod`, if `QR_SECRET` is still the
placeholder, or if Clerk is selected without `CLERK_ISSUER` and `CLERK_JWKS_URL`. A failed
start with a clear message in the logs means one of these.

## 3. Make your first organizer

Everyone who signs in starts as a `participant`; roles are never read from the sign-in token.
After you have signed in once (so your user exists), promote yourself in the database. In
Render open the database, copy its *External* connection command, and run:

```sql
UPDATE users SET role = 'admin' WHERE email = 'you@example.com';
```

Use `organizer` instead of `admin` for people who should only manage events. Volunteers who
scan QR codes get `volunteer` the same way.

## 4. Rate limiting behind Render (do this once)

Render puts its own proxy in front of the API, so the API must be told how many proxies to
trust when working out a visitor's IP. Get it wrong and either everyone shares one limit
(60 requests a minute for the whole site) or the limit can be dodged.

1. Deploy with `TRUSTED_PROXY_HOPS=1`.
2. Trigger a rate limit from your own machine, for example by sending the same registration
   request 11 times quickly with a signed-in user.
3. In the API logs find the line `rate limited ... ip=... x_forwarded_for=...`.
4. `ip` should be **your** public address. If it is a Render or CDN address instead, the proxy
   chain is longer than assumed: raise `TRUSTED_PROXY_HOPS` by one and repeat. The app also logs
   a warning at start-up when it runs in production with `TRUSTED_PROXY_HOPS=0`.

## 5. Check it works

- `GET https://<your-api>.onrender.com/healthz` returns `{"status":"ok"}`.
- `GET /events` returns `{"items":[],"next_cursor":null}`.
- Sign in through your frontend, call `GET /me` with the Clerk token as `Authorization: Bearer ...`,
  create an event as an admin, register as a participant, and confirm the email arrives with a QR.
- If emails do not arrive: the worker logs show each failure and retry
  (`outbox N failed (attempt k)`); after 8 attempts a row becomes `failed` and stays in the
  `outbox` table with its `last_error`.

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `ENV` | `dev` | `prod` turns on the start-up safety checks |
| `AUTH_MODE` | `dev` | `clerk` in production |
| `DATABASE_URL` | local | `postgres://` and `postgresql://` URLs are converted to the async driver |
| `REDIS_URL` | empty | empty means in-memory rate limiting and cache (single process only) |
| `QR_SECRET` | placeholder | required to be changed in prod |
| `RATE_LIMIT_USER_PER_MIN` / `RATE_LIMIT_IP_PER_MIN` / `RATE_LIMIT_CHECKIN_PER_MIN` | 10 / 60 / 120 | SPEC 5 |
| `TRUSTED_PROXY_HOPS` | 0 | see section 4 |
| `CACHE_ENABLED`, `CACHE_TTL_SECONDS` | true, 3 | browse-page cache |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` | 20, 20 | per process; processes x (size + overflow) must stay under the database's connection limit |
| `WEB_CONCURRENCY` | 1 | uvicorn worker processes |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_STARTTLS`, `MAIL_FROM` | MailHog | worker only |
| `OUTBOX_POLL_SECONDS`, `OUTBOX_MAX_ATTEMPTS` | 2, 8 | worker only |
