# M6 Frontend plan

> **Status: built and deployed.** The plan below is the original design and still explains why the API
> gained CORS, richer `/me` endpoints and organizer reads (M6a, done). Two decisions changed on the
> way: Lovable produced only the first shell and its credits ran out, so everything with logic was
> written and tested in `frontend/` here (77 tests), and the hosting is Vercel, not Lovable. The look
> was redone afterwards (black and yellow, seat counts as the loudest type). What was built, and the
> bugs found by running it, are in decisions.md entries 57 to 59. `lovable_kit/` is kept only as the
> record of how the first version was briefed.

Goal: a website students, organizers and volunteers can use on a phone, built by Lovable, that
cannot lose or double a registration even when the server is asleep, the token has expired or the
network drops. I design and verify; Lovable only draws screens.

## 1. What I found in the backend (gaps the frontend cannot work around)

I read every router. The API is complete for the backend, but a browser client hits these walls:

| # | Gap | Why it breaks the site | Fix (M6a, backend, before Lovable) |
|---|---|---|---|
| 1 | **No CORS.** | Every call from the Lovable domain is blocked by the browser. | `CORS_ALLOW_ORIGINS` + `CORS_ALLOW_ORIGIN_REGEX` settings; allow headers `Authorization`, `Content-Type`, `Idempotency-Key`; expose `Retry-After`, `Content-Disposition`, `X-Cache`. No cookies, so no credentials. |
| 2 | `GET /me/registrations` returns only `category_id`. There is no category-to-event lookup. | "My registrations" could not show an event or sport name without downloading every event. | Add `event_id`, `event_name`, `event_starts_at`, `venue`, `category_name`, `sport`, `team_id`, `team_name` to each row. |
| 3 | **No "my teams".** A forming team has no registration, so it is invisible after a page reload. | A captain who refreshes loses their invite code and cannot register the team. | `GET /me/teams` (teams I captain or belong to, with `invite_code` only for the captain, member count, status, category and event names). |
| 4 | `GET /events` shows only published events and `GET /events/{id}` returns 404 for drafts. | An organizer cannot see their draft or closed events, so cannot add categories or publish. | `GET /organizer/events` (all statuses) and `GET /organizer/events/{id}` (uncached, includes drafts). |
| 5 | The CSV needs the `Authorization` header. | A plain download link returns 401. | Frontend downloads it with `fetch` as a blob. No backend change. |
| 6 | Roles can only be changed in the database. | Nobody can become organizer or volunteer from the site. | Keep it manual and document the SQL (a handful of staff). An admin endpoint is optional and later. |
| 7 | 500 responses and Render's cold-start page carry no CORS headers. | The browser reports only "network error" for them. | Frontend treats any network failure on a POST as "outcome unknown" and retries with the **same** idempotency key. |

Each fix gets tests (preflight request, allowed and blocked origins, the new fields, role gating,
no draft leaks through the cached public endpoint). Existing behaviour does not change; the
response additions are optional fields. Ruff and the full suite stay green. This needs your OK
(CLAUDE.md: nothing outside SPEC.md without asking).

## 2. Architecture

- Lovable project: Vite + React + TypeScript + Tailwind + shadcn/ui (Lovable's default).
- **No Supabase, no Lovable Cloud.** The only backend is the EntriX API.
- Auth: Clerk (`@clerk/clerk-react`) with the publishable key. A fresh `getToken()` before every
  request (session tokens live 60 seconds, so never store them).
- Server state: TanStack React Query. Roles come from `GET /me` (the database), never from Clerk.
- The non-visual layer (API client, types, error messages, idempotency, cold-start handling) is
  **written by me** in `lovable_kit/FRONTEND_SPEC.md` and pasted verbatim. Lovable must not
  rewrite it. This is what makes the site not fail: the risky logic is not left to generation.
- Config in `src/config.ts` (API URL and Clerk publishable key are public values, so hard-code
  them; this avoids Lovable's environment variable quirks).

## 3. Screens (every component)

| Route | Who | Content |
|---|---|---|
| `/` | public | Event list (cursor "Load more"), registration status badge computed from open/close times |
| `/events/:id` | public | Event detail, categories with seats left / waitlist, Register, Create team, Join team |
| `/me` | signed in | Profile form (name, college, roll no, phone) |
| `/my/registrations` | signed in | Status, waitlist position, QR (cached offline), Cancel |
| `/my/teams` | signed in | Invite code (copy/share), members, Register team, Leave, Cancel team |
| `/organizer` | organizer | Events (all statuses), create event |
| `/organizer/events/:id` | organizer | Edit, status step (draft, published, closed), categories (add, edit capacity), stats, registrations table with filters, CSV |
| `/scan` | volunteer, organizer | Event picker, camera scanner, result banner, manual token field |
| `*` and an error boundary | all | Not found, "something went wrong" with reload |

Layout: mobile first (most users are on phones at the venue), bottom navigation on mobile, top bar
on desktop, light and dark theme, 44 px tap targets, no horizontal scroll.

## 4. Failure matrix (this is the checklist Lovable is held to)

| Situation | Required behaviour |
|---|---|
| Render asleep (about 33 s) | After 4 s show "Waking the server, this can take up to 40 s"; GETs retry with backoff up to 60 s; never show a blank screen |
| Token expired (`401 token_expired`) | Get a fresh token and retry once; if it still fails, send to sign-in |
| Click Register | New `Idempotency-Key` per attempt; button disabled while pending; on network error or 5xx **reuse the same key** for the retry; a new key only after a definitive answer |
| `409 idempotency_in_progress` | Wait 1 s, resend the same key |
| `429` | Disable the action and show a countdown from `Retry-After` |
| `category_full` and waitlist off | Show "Full", disable Register |
| Registered, waitlisted | Show "You are #N on the waitlist"; promotion appears on the next refetch |
| `registration_closed`, `already_registered`, `already_in_team`, `team_full`, `roster_locked`, ... | Mapped to plain-language messages (table in the spec); never show raw JSON or a stack |
| Seat count is stale (cached up to 3 s) | Refetch event after every registration attempt; the server stays the authority |
| Double click, back button, refresh mid-request | Impossible to double register: one in-flight mutation lock plus idempotency |
| Camera denied or no HTTPS | Scanner falls back to manual token entry with a clear message |
| Scanning the same QR repeatedly | 3 s debounce; `already_checked_in` shows amber, not red |
| Offline at the venue | Participant QR works from the local cache; scanner shows "no connection" and keeps the camera running |
| Forbidden page (role) | Redirect with a message; the real enforcement is the server's 403 |
| Unknown error | Generic message plus a "Try again" button; the error code is shown small for support |

## 5. Order of work

1. **M6a backend** (DONE, 324 tests pass; needs deploy): CORS, `/me/registrations` fields, `/me/teams`, organizer endpoints, tests,
   deploy, add `CORS_ALLOW_ORIGINS` on Render. Smoke-test CORS with `curl`.
2. **M6b kit** (done in this commit): `lovable_kit/FRONTEND_SPEC.md` and `lovable_kit/PROMPTS.md`.
3. **M6c Lovable build** (you, 6 prompts): foundation, public, participant, organizer, scanner, QA.
4. **M6d verification** (together): run the QA checklist on a phone against the live API, fix list,
   update docs.

## 6. Acceptance

- A new user can sign up, set a profile, register for an individual category, see the QR, and cancel.
- A team captain can create a team, a second account can join with the code, and the captain can register it.
- An organizer can create an event, add categories, publish, watch stats and download the CSV.
- A volunteer can scan a QR and see success, then amber on a second scan.
- Every row of the failure matrix has been exercised at least once (I will give you the exact steps).
- No secret in the frontend repo (only the publishable key and the public API URL).

## 7. Known limits that are not frontend problems

- Clerk development instance: 100 users and a "development" banner. A real mass event needs a
  domain and a Clerk production instance (or another sign-in provider). Deferred, as agreed.
- Brevo sends from a shared sender without a domain; some inboxes may filter. Not blocking.
- Render free sleeps; the event-day checklist in DEPLOY.md still applies.
