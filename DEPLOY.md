# Deploying EntriX for free

`render.yaml` is the **free** setup: one free Render web service that runs the API, the email
worker and the database migrations, plus Neon for the database, Clerk for sign-in and Brevo for
email. The full paid architecture (separate worker, Redis, Render Postgres) is `render.paid.yaml`
and is described at the end.

> **Not tested on your Render account.** I could not deploy for you. The pieces were checked
> against the providers' documentation and by running the same Docker image locally (migrations
> on an empty database, the worker inside the API, a bad database password refusing to serve).
> The first real deploy may still need small adjustments; send me the failing log lines.

## What the free setup is, and what it costs you

```
Render free web service  =  API + email worker + migrations      (one process)
Neon free Postgres                                               (does not expire)
no Redis                  →  rate limits and cache live in memory (fine for one process)
Brevo HTTPS API           →  email (Render free blocks SMTP ports 25, 465 and 587)
Clerk                     →  sign-in
```

| Limit | Source | What it means for you |
|---|---|---|
| Free web services sleep after **15 minutes** without traffic; waking takes **about a minute** | [Render](https://render.com/docs/free) | The first request after a quiet spell is slow. Warm it up before an event (below). |
| **750 free instance hours** per month, shared by the workspace | [Render](https://render.com/docs/free) | One always-on service uses about 744. Do not add a second free web service. |
| Render may restart a free service at any time | [Render](https://render.com/docs/free) | Rate-limit counters and the cache reset. Queued emails survive: they are in the database. |
| No background workers, no pre-deploy command, no SMTP on free | [Render](https://render.com/docs/free), [deploys](https://render.com/docs/deploys) | That is why the worker runs inside the API, migrations run at start, and email goes over HTTPS. |
| Neon free: **100 compute-hours** a month, suspends after **5 idle minutes**, 1 GB | [Neon](https://neon.com/docs/introduction/plans) | The first query after a pause is slower. Idle polling is turned off so it can sleep. |
| Brevo free: **300 emails a day** | [Brevo](https://www.brevo.com/features/email-api/) | A launch with more registrations than that sends the rest the next day, automatically. |
| Clerk development instance: **100 users** | [Clerk](https://clerk.com/docs/guides/development/managing-environments.md) | Fine for testing and a small pilot; a mass event needs a production instance (a domain). |

**About that $34.50.** When a `plan:` is left out of a Blueprint, Render uses a paid default
(`0.5c-512mb` for a web service). The earlier Blueprint left plans out, so it priced paid
instances. `render.yaml` now sets `plan: free` explicitly.

## 1. Accounts and values to collect

### Neon (database)
1. Create a project. **Pick the region nearest the Render region in `render.yaml`**
   (`singapore` by default; edit `region:` if you choose another). Every request makes several
   database round trips, so distance costs real time.
2. Copy the **direct** connection string, not the pooled one (pooled hostnames contain
   `-pooler`). Neon's own docs recommend a direct connection for migrations, and the app relies
   on row locks working exactly as tested.
3. Paste it as-is as `DATABASE_URL`. The app converts `postgres://`, rewrites `sslmode=require`
   to what the driver wants and drops `channel_binding`. (Verified: the unconverted form fails
   with `unexpected keyword argument 'sslmode'`.)

### Clerk (sign-in)
1. Create a Clerk application and enable the sign-in methods you want.
2. **Add email and name to the session token.** Clerk's default token has neither, and the API
   needs the email. In the Clerk dashboard open *Sessions*, then *Customize session token*, and add:
   ```json
   { "email": "{{user.primary_email_address}}", "name": "{{user.full_name}}" }
   ```
   Without `email` the API answers `401 missing_email_claim` (the message says what to fix).
3. Note your **issuer** (Frontend API URL, `https://...`) and **JWKS URL**
   (`<issuer>/.well-known/jwks.json`) for `CLERK_ISSUER` and `CLERK_JWKS_URL`. Open the JWKS URL
   in a browser: it should show JSON containing `"keys"`. Clerk's OpenID discovery document at
   `<issuer>/.well-known/openid-configuration` states the exact issuer string.

> **Known limit, deferred for now: Clerk development instances.** A new Clerk application is a
> *development* instance, which [Clerk caps at 100 users](https://clerk.com/docs/guides/development/managing-environments.md)
> and does not consider suitable for production. A *production* instance needs
> [a domain you own](https://clerk.com/docs/guides/development/deployment/production) (DNS records).
> That is fine for building, testing and a small pilot, but **not for a real mass event.** Before
> one, either get a domain (this also lets you authenticate your Brevo sender so mail comes from
> your own address), or switch to a sign-in provider that has no such requirement (the verifier
> accepts any RS256 JWKS issuer, so that is a modest change). The GitHub Student Developer Pack has
> historically included a free domain; check whether that offer is still current.

### Brevo (email), and why you must test it first
Without a domain of your own, Brevo cannot authenticate a Gmail sender address. It then
[substitutes its own sender identity](https://community.brevo.com/t/email-being-sent-with-t-sender-sib-com/783),
so **whether your emails reach the inbox or the spam folder depends on the recipient's provider**,
and I cannot predict that. Find out before an event:

1. In Brevo, add and verify your sender address (*Senders, Domains and Dedicated IPs*).
2. Create an **API key** (*SMTP & API*, then *API keys*). It is not the SMTP key.
3. Give the script the three settings. The safest way, because nothing is saved to disk, is to
   set them for one PowerShell window only:
   ```powershell
   $env:EMAIL_BACKEND = "brevo"
   $env:BREVO_API_KEY = "<your key>"
   $env:MAIL_FROM = "<the sender you verified>"
   ```
   Alternatively copy `.env.example` to `.env` (git-ignored) and fill in `EMAIL_BACKEND=brevo`,
   `BREVO_API_KEY` and `MAIL_FROM`. With a Brevo key in `.env`, a worker you run locally sends
   **real** emails through Brevo instead of to MailHog, so delete those lines afterwards. The
   test suite ignores `.env`, so it is unaffected either way.
4. Send a real test to **mailboxes you own**, one for each kind of address your students use
   (the script refuses the example addresses used in these docs):
   ```bash
   python -m scripts.send_test_email your.name@gmail.com your.name@outlook.com your.name@college.edu
   ```
   The first line it prints must say `backend=brevo`. If it says `backend=smtp`, the settings were
   not picked up and nothing was sent.
5. Look in each **inbox and spam folder**. Note the "From" line (it may show a Brevo address).

If the results are poor, the options are: get a domain and authenticate it in Brevo (then mail
comes from your own address and deliverability is normally good), or ask me to add a Gmail API
backend (free, sends as a real Gmail account, but needs a Google Cloud OAuth setup). **Never paste
the key into a chat or commit it.**

Brevo's API cannot embed images in the email body, so the QR code arrives as an **attachment**
(`qr.png`), and the email also shows the code as text. (The SMTP backend used locally still
embeds it inline.)

### A secret for QR codes
```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```
If it ever changes, QR codes already emailed stop verifying.

## 2. Create the service on Render

1. Push the repository to GitHub.
2. In Render: *New*, then *Blueprint*, pick the repository. Render reads `render.yaml` and asks
   for the values marked `sync: false`:

   | Variable | Value |
   |---|---|
   | `DATABASE_URL` | the Neon **direct** connection string |
   | `QR_SECRET` | the secret above |
   | `CLERK_ISSUER`, `CLERK_JWKS_URL` | from Clerk |
   | `BREVO_API_KEY`, `MAIL_FROM` | from Brevo |
   | `TRUSTED_PROXY_HOPS` | `1` to start, then check (section 4) |

3. Watch the first deploy's logs. You should see Alembic apply the migration
   (`Running upgrade  -> 0001`), then `outbox worker running inside the API process`.

The app refuses to start (with the reason in the log) if `AUTH_MODE=dev` with `ENV=prod`, if
`QR_SECRET` is still the placeholder, if Clerk settings are missing, or if `EMAIL_BACKEND=brevo`
has no `BREVO_API_KEY`. If the migration fails the container exits instead of serving.

## 3. Make your first organizer

Everyone starts as a `participant`; roles are never read from the sign-in token. Sign in once so
your user exists, then in Neon's SQL editor:

```sql
UPDATE users SET role = 'admin' WHERE email = 'you@example.com';
```

Use `organizer` for people who manage events and `volunteer` for people who scan QR codes.

## 3b. Test a real sign-in (before there is a frontend)

`tools/clerk_test/index.html` is a small development page: it signs you in with Clerk, shows your
session token, checks that it carries the claims the API needs, and builds PowerShell commands so
you can call the deployed API as yourself.

```powershell
python -m http.server 3000 --directory tools/clerk_test
```
Open http://localhost:3000, sign in, and read the checklist:

- **email claim** must be a tick. If not, add the claims in Clerk (section 1) and sign in again.
- **issuer** must be a tick. If it shows a different value, set `CLERK_ISSUER` on Render to
  exactly the value in the token.

Then press a "Copy" button and paste into PowerShell **within the minute** (Clerk session tokens are
short-lived; the page refreshes them for you). `GET /me` should return your user with role
`participant`. The page's publishable key (`pk_test_...`) is public by design; it is set at the top
of the file. It does not call the API from the browser, because that needs CORS, which arrives with
the real frontend.

## 3c. Smoke-test the live API

`scripts/smoke_test_deployed.py` walks one registration through its whole life on the real service
(create and publish an event, add a category, register, replay the same request, try a duplicate,
scan the QR twice, try to cancel after check-in, read the organizer stats and CSV, close the
event), printing `[ OK ]` or `[FAIL]` for each of about 20 steps. Your user must be an `admin` or
`organizer` (section 3).

1. On the test page click **"Copy: Remember the token ..."** and paste it into PowerShell (it sets
   `$t`). Do the next command within the minute:
   ```powershell
   $env:ENTRIX_TOKEN = $t
   python -m scripts.smoke_test_deployed https://YOUR-SERVICE.onrender.com
   ```
2. Check your inbox (and spam) for **"You're in: Smoke Singles (SMOKE TEST ...)"**. That email
   proves the whole chain on the live service: the registration, the worker inside the API, and
   Brevo over HTTPS. The script cannot see your mailbox.
3. It leaves one closed event named `SMOKE TEST <time>` behind (events have no delete endpoint).

## 4. Rate limiting behind Render (do this once)

Render's proxy sits in front of the app, so the app must be told how many proxies to trust to
work out a visitor's IP. Wrong, and everyone shares one limit (60 requests a minute for the whole
site), or the limit can be dodged.

1. Deploy with `TRUSTED_PROXY_HOPS=1`.
2. Trigger a limit from your own machine (send the same registration 11 times quickly).
3. In the logs find `rate limited ... ip=... x_forwarded_for=...`.
4. `ip` should be **your** public address. If it is a Render or CDN address, raise
   `TRUSTED_PROXY_HOPS` by one and repeat. At start-up the app also warns if it runs in production
   with `TRUSTED_PROXY_HOPS=0`.

## 5. Event-day checklist

A free service that has been idle is asleep, and so is Neon.

- **30 minutes before registration opens:** open `https://<your-api>/healthz` once. It wakes Render
  and, because it queries the database, Neon too. Then the first student does not hit two cold starts.
- **During registration:** keep the service awake by requesting `/livez` every 10 minutes or less
  (a free uptime monitor you switch on for the event, or `curl` it yourself). `/livez` does not
  touch the database, so pinging it does not use up Neon's compute hours.
- **Afterwards:** switch the monitor off. Running it all month would use almost all of the 750 hours.
- **Email volume:** if more than 300 confirmations are queued in a day, the rest wait and go out
  automatically once Brevo accepts them again (the logs say `deferred ... without using an attempt`).

## Troubleshooting

| You see | Meaning |
|---|---|
| `outbox ... deferred ... quota` | Brevo's daily cap or rate limit. Nothing is lost; it retries. |
| `Brevo rejected the API key ...` | Wrong or revoked `BREVO_API_KEY`. Fix it; queued emails then send. |
| `Brevo ... valid sender email required` (or the app refusing to start with `MAIL_FROM must contain an email address`) | `MAIL_FROM` is empty or malformed. The classic cause: a value pasted into Render's dashboard **with quotes** (`"EntriX <you@x.com>"`). A `.env` file strips quotes, a dashboard does not, so it works locally and fails on Render. Set it to `EntriX <you@x.com>` or just the address, with no quotes. The app now strips stray quotes and refuses to start on an unusable value. To resend emails that already ran out of attempts, in Neon: `UPDATE outbox SET status = 'pending', attempts = 0, next_attempt_at = now() WHERE status = 'failed';` then redeploy (the worker sends on start-up). |
| `Brevo returned 400 ...` | Usually the sender: use exactly the address you verified in `MAIL_FROM`. After 8 tries a row is marked `failed` (kept in the `outbox` table with `last_error`). |
| `401 missing_email_claim` | The Clerk session token has no `email` claim (section 1). |
| Very slow first request | Cold start (Render about a minute, Neon a moment). See the checklist. |
| `Internal Server Error` (a plain-text 500) right after a quiet spell | The database had closed idle connections (Neon suspends after 5 idle minutes) while the app stayed up. Fixed by `pool_pre_ping` (the pool tests a connection before using it); if you still see it, send the traceback from the Render logs. |
| Emails never arrive | Check the logs for the lines above, then spam folders (section 1). |

## Backups

Free Render Postgres has none, and I did not find Neon's free-plan backup policy in the pages I
read, so assume there is no safety net. Before an event, take a dump yourself
(`pg_dump "<neon direct url>" > backup.sql`).

## If you outgrow it: the paid architecture

`render.paid.yaml` is the full design: separate always-on worker, Redis for shared rate limits,
managed Postgres, pre-deploy migrations, SMTP. **Set `plan:` on every service first** (see the
warning at the top of that file), then use *New, Blueprint* and set the file path to
`render.paid.yaml`. The code is the same; only environment variables change
(`RUN_WORKER_IN_API=false`, `REDIS_URL` set, `EMAIL_BACKEND=smtp`).

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `ENV` | `dev` | `prod` turns on the start-up safety checks |
| `AUTH_MODE` | `dev` | `clerk` in production |
| `DATABASE_URL` | local | `postgres://` and `postgresql://` URLs, `sslmode` and `channel_binding` are handled |
| `RUN_MIGRATIONS_ON_START` | false | container applies migrations before serving; for hosts with no pre-deploy step |
| `RUN_WORKER_IN_API` | false | run the email worker inside the API process |
| `OUTBOX_POLL_SECONDS`, `OUTBOX_IDLE_POLL_SECONDS` | 2, 2 | longest idle sleep; free tier uses 3600 (a new registration wakes the worker at once) |
| `OUTBOX_MAX_ATTEMPTS` | 8 | real failures only; quota and credential errors do not count |
| `EMAIL_BACKEND` | `smtp` | `brevo` sends over HTTPS |
| `BREVO_API_KEY` | empty | required when `EMAIL_BACKEND=brevo` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_STARTTLS`, `MAIL_FROM` | MailHog | SMTP backend (and `MAIL_FROM` for both) |
| `REDIS_URL` | empty | empty means in-memory rate limiting and cache: single process only |
| `QR_SECRET` | placeholder | required to be changed in prod |
| `CLERK_ISSUER`, `CLERK_JWKS_URL` | empty | required when `AUTH_MODE=clerk` |
| `RATE_LIMIT_USER_PER_MIN` / `RATE_LIMIT_IP_PER_MIN` / `RATE_LIMIT_CHECKIN_PER_MIN` | 10 / 60 / 120 | SPEC 5 |
| `TRUSTED_PROXY_HOPS` | 0 | see section 4 |
| `CACHE_ENABLED`, `CACHE_TTL_SECONDS` | true, 3 | browse-page cache |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` | 20, 20 | per process; `render.yaml` uses 5 and 5 |
| `WEB_CONCURRENCY` | 1 | **must stay 1** without Redis: each process would keep its own counters |
