# How to drive Lovable (free tier) with the fewest credits

Lovable's free plan gives a small number of credits (a few per day, with a monthly cap; check the
counter in your account, it changes). Each message costs credits, so the plan is **six big,
precise prompts** and a short list of cheap fixes, not a long conversation.

## Before you start (once, 15 minutes, no credits)

1. Backend first. Tell me "M6a go" and I build and deploy CORS, the extra endpoints and tests.
   Do not start Lovable before that, or the screens will call endpoints that do not exist.
2. In Render, add `CORS_ALLOW_ORIGINS` once you know your Lovable URL (I will tell you the exact
   value; until then a regex covering `*.lovable.app` and `*.lovableproject.com` is set).
3. Make staff accounts. Each person signs in once on the site first, then run in Neon SQL:
   ```sql
   UPDATE users SET role = 'organizer' WHERE email = 'organizer@example.com';
   UPDATE users SET role = 'volunteer' WHERE email = 'volunteer@example.com';
   ```
4. Have two or three real test accounts (Gmail plus-addresses work: `you+a@gmail.com`).
5. Phone with Chrome or Safari for the scanner test.

## Creating the project

1. lovable.dev, sign in, **New project**. In the first box paste **Prompt 0** below. Do not
   connect Supabase when it offers to. If it asks, answer "no backend".
2. Open **Project Settings, Knowledge** (called "Project knowledge" or "Custom knowledge") and paste
   the entire content of `lovable_kit/FRONTEND_SPEC.md`. Every later prompt then says "follow the
   project knowledge" instead of repeating it, which saves credits and stops drift.
   - If your plan has no knowledge box, run Prompt 0 as written (it creates `docs/FRONTEND_SPEC.md`
     from your paste); every prompt then says "follow docs/FRONTEND_SPEC.md".
3. Turn on **GitHub sync** (top right) to a new empty repo. It gives you a free backup and lets me
   review the code. Edits made in Lovable push automatically.

## Rules that save credits

- Send the prompts below in order. **Wait for each to finish and test it before the next.**
- One concern per prompt. Never "also add...".
- If something is wrong, use **Fix template** (under 80 words). Never re-send a whole prompt.
- Use the Preview and the browser console to look; use **Chat/Plan mode only for questions**.
- Do not click "Fix errors" repeatedly. If the same error survives two tries, stop and send me the
  console text and a screenshot; I will give you the exact one-line fix prompt.
- Do not ask Lovable to "make it prettier" until Prompt 6. Design is one pass at the end.
- The Visual Edits tool (free for text and colours in many plans) is cheaper than a prompt for
  small wording or colour changes.

---

## Prompt 0: create the project (paste into the first box)

```
Build a mobile-first web app called EntriX, a sports-event registration site. The complete
specification is below and is the single source of truth: follow it exactly, including its hard
rules (no Supabase, no Lovable Cloud, no backend of your own; only the listed packages).
Create the files in section 1 of the spec verbatim (config.ts, types.ts, lib/errors.ts, lib/api.ts,
lib/idempotency.ts) and wire the app as described in section 2. Put the full spec text into
docs/FRONTEND_SPEC.md.
For now build only: the app shell (top bar on desktop, bottom navigation on mobile with Events,
My registrations, My teams and a Staff menu that shows only for role organizer, admin or
volunteer), Clerk sign-in/out with the UserButton, the AuthBridge, the ServerWakingBanner, the
root error boundary, a Not Found page, and empty placeholder pages for each route. The home
page can say "EntriX". Do not build any other feature yet.

[PASTE THE WHOLE OF lovable_kit/FRONTEND_SPEC.md HERE]
```

**Check:** the preview loads, "Sign in" opens the Clerk modal, after sign-in your avatar shows.
Open the browser console: no red errors. Then say "ok" to me.

## Prompt 1: public events and registration

```
Follow the project knowledge (docs/FRONTEND_SPEC.md). Do not edit the provided lib files.
Build the public and registration flow:
1. "/" Events list using api.listEvents with a "Load more" button (cursor). Each card: name, venue,
   date range in local time, and a badge: "Opens <date>" before reg_opens_at, "Registration open"
   between, "Registration closed" after. Loading skeleton, empty state ("No events yet"), error
   state with Retry.
2. "/events/:id" using api.getEvent. Header with details, then one card per category: name, sport,
   "<seats_left> of <capacity> seats left", a progress bar, and the right action:
   - individual with seats: "Register"
   - individual, seats_left 0, waitlist_enabled: "Join waitlist"
   - individual, seats_left 0, waitlist off: disabled "Full"
   - team category: "Create team" (dialog asking for a team name) and "Join with code" (dialog
     asking for the invite code)
   - not signed in: the button opens the Clerk sign-in instead
   - registration not open: disabled with the reason ("Opens <date>" or "Closed")
3. Register uses useIdempotentAction with api.register. While pending the button shows a spinner.
   On success show a confirmation dialog: "You're in!" (confirmed) or "You're on the waitlist,
   position N" (waitlisted) with a "View my registrations" button, then refetch the event. On error
   show messageFor(error) in a toast. Treat error.status 429 specially: disable the button and show
   a countdown using error.retryAfter.
4. Create team and Join team use api.createTeam and api.joinTeam, then navigate to /my/teams.
Both pages must work signed out for viewing. Do not build My registrations or teams pages yet.
```

**Check:** the list shows your smoke-test event; open it; sign in; register; the dialog appears;
double-click quickly (only one request in the Network tab); register again (see the "already
registered" message, no crash).

## Prompt 2: my registrations, QR, profile

```
Follow the project knowledge. Build:
1. "/my/registrations" (signed in only; signed-out users see a Sign in prompt). List from
   api.myRegistrations with Load more. Card per registration: event name, category name, sport,
   date, venue, status badge, "Waitlist position N" when waitlisted, team name if any.
   Actions: "Show QR" (confirmed or checked_in only) and "Cancel" (confirmed or waitlisted), where
   Cancel asks for confirmation first, calls api.cancelRegistration, then refetches.
2. "Show QR" opens a full-screen dialog with a large QR code (qrcode.react, 280px, white
   background, high error correction) encoding exactly the token from api.qr(registration_id),
   plus the event, category and participant name. Cache the token in localStorage under
   "qr:<registration_id>" and show the cached token immediately while refreshing, so it still works
   with no internet. If there is neither a cached token nor a connection, show a clear message.
   Keep the dialog brightness-friendly (white card) and add a "checked in" green state when the
   status is checked_in.
3. "/me" profile form: name (required), college, roll number, phone; save with api.patchMe;
   success toast; show the email read-only. If the name looks empty or auto-generated, show a
   gentle "Complete your profile" notice on the home page for signed-in users.
Do not touch other pages.
```

**Check:** your registration shows; QR appears; switch the browser to offline (DevTools, Network,
Offline) and reopen the QR: it still shows; cancel and see the status change.

## Prompt 3: teams

```
Follow the project knowledge. Build "/my/teams" (signed in only) using api.myTeams.
Card per team: name, event and category, status badge, "N of min-max members", members list when
expanded (api.getTeam). If is_captain, show the invite code in a monospace box with Copy and Share
buttons (navigator.share when available), and "Register team" (disabled until member_count >=
team_size_min, with the reason shown) using useIdempotentAction with api.registerTeam; success
shows the same confirmed or waitlisted dialog as individual registration. Non-captains see
"Leave team" with confirmation (api.leaveTeam). Captains see "Cancel team" with confirmation
(api.cancelTeam). Hide leave/cancel once status is registered where the spec says the roster is
locked, and show messageFor(error) if the server refuses. Empty state: "You are not in any team",
with a link to events. Refetch after every action. Do not touch other pages.
```

**Check (needs two accounts):** account A creates a team; copy the code; account B joins it;
A sees two members; A registers the team.

## Prompt 4: organizer

```
Follow the project knowledge. Build the organizer area, visible and reachable only when useMe().role
is organizer or admin (others get a "Not allowed" page and a link home):
1. "/organizer": api.orgEvents list with status badges (draft, published, closed) and a
   "New event" dialog: name, slug (auto-generated from the name, lowercase letters, numbers and
   hyphens, editable), description, venue, and four date-time pickers (starts, ends, registration
   opens, registration closes). Validate before sending: starts < ends, opens < closes, closes <=
   ends. Convert local times to UTC ISO strings. Show server validation messages.
2. "/organizer/events/:id" with tabs:
   - Overview: edit event fields (api.patchEvent) and a single button to move to the next status
     (draft to published to closed), with a confirmation that explains it. No backward moves.
   - Categories: list with seats; "Add category" dialog (name, sport, participation individual or
     team, team min and max shown only for team, capacity, waitlist toggle); edit capacity and
     waitlist with api.patchCategory (explain that raising capacity promotes the waitlist and that
     capacity cannot go below confirmed).
   - Stats: api.stats as cards and a simple bar chart (recharts) of confirmed, waitlisted and
     checked in per category; refresh every 15 seconds while the tab is visible.
   - Registrations: api.registrations table with filters (category, status), Load more, and on
     mobile a stacked card layout instead of a wide table. A "Download CSV" button using
     api.downloadCsv with a spinner and an error toast.
Do not touch other pages.
```

**Check (organizer account):** create an event, add a category, publish, open the public page in a
private window and see it, register from another account, see stats change, download the CSV.

## Prompt 5: volunteer scanner

```
Follow the project knowledge. Build "/scan", visible and reachable only for roles volunteer,
organizer, admin.
1. Step 1: event picker. Use api.orgEvents for organizer/admin and api.listEvents for volunteers.
   Remember the chosen event in localStorage.
2. Step 2: scanner using html5-qrcode with the rear camera (facingMode environment), full-width
   viewfinder, continuous scanning. On each decoded text call api.checkIn(eventId, text).
   Ignore the same text for 3 seconds (debounce) and ignore scans while a request is pending.
3. Result banner (aria-live, large, readable at arm's length), auto-hides after 4 seconds:
   - success: green, participant name and category, "Checked in"
   - already_checked_in true: amber, "Already checked in" with name
   - error: red, messageFor(error) (wrong event, invalid QR, cancelled, rate limited, offline)
   Add a short vibration (navigator.vibrate) and a counter "Checked in this session: N".
4. If the camera is denied or unavailable (or the page is not HTTPS), show a clear message and
   fall back to a text box where the volunteer can paste a token and press Check in.
5. Always stop the camera when leaving the page. Provide a "Switch camera" button.
Do not touch other pages.
```

**Check on your phone:** open the published URL, sign in as volunteer or organizer, show a QR from
another device or window; first scan green, second amber.

## Prompt 6: polish and hardening (the last paid prompt)

```
Follow the project knowledge. Do a polish pass without changing behaviour or the provided lib files:
(1) consistent spacing, type scale and the single accent colour via design tokens; (2) dark mode
works everywhere; (3) every page has loading, empty and error states as the spec requires;
(4) all inputs have labels, all icon buttons have aria-labels, focus outlines are visible;
(5) set the page <title> per route and add a favicon and a meta description; (6) remove unused
code and console.log calls; (7) make sure no page scrolls horizontally at 360px wide;
(8) add a footer with "EntriX" and a short note "Times shown in your local time zone".
Report what you changed in five lines.
```

## Fix template (cheap, use for any bug)

```
Bug on <route>: <what I did>. Expected: <expected>. Actual: <actual or exact error text>.
Fix only this, in the file that owns it. Do not change lib/api.ts, errors.ts, idempotency.ts or
types.ts, and do not refactor.
```

## Final QA on a phone (give me the results)

Run each against the live API. Tell me which fail.
1. Cold start: wait 20 minutes, open the site: the "waking the server" banner appears, then the list loads.
2. Sign up fresh, register, double-tap Register: one registration.
3. Fill a category (capacity 1), second account gets the waitlist; cancel the first, second is promoted.
4. Airplane mode, then Register: friendly network error; turn it back on, tap again: succeeds once.
5. Tap Register 12 times quickly with different accounts' tokens or via the test page: the 429 countdown appears.
6. Closed event: button disabled with the reason.
7. QR works offline; check-in green then amber.
8. Organizer: create, publish, edit capacity upward, CSV opens in Excel.
9. A participant opens `/organizer` and `/scan`: sees "Not allowed".
10. Rotate the phone, switch dark mode: nothing breaks.

## If you run out of free credits

Work stops at the end of the day's credits; the order above is built so each stage is usable alone:
after Prompt 1 students can register; after Prompt 2 they have QR codes; Prompt 5 is needed on the
event day. Prompts 3, 4 and 6 are the ones to drop or do the next day. Because of GitHub sync, you
can also hand me the repo and I will make small edits directly with no credits.
