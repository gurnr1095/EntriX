# EntriX frontend spec (Project Knowledge for Lovable)

You are building the web client for the EntriX sports-event registration API. This document is the
single source of truth. Follow it exactly. When it conflicts with your habits, this document wins.

## 0. Hard rules

1. **Do not use Supabase, Lovable Cloud, or any other backend or database.** The only backend is
   the EntriX REST API below. Do not create tables, edge functions or auth tables.
2. Stack: React + TypeScript + Tailwind + shadcn/ui + React Router + TanStack React Query. Add only
   these packages: `@clerk/clerk-react`, `qrcode.react`, `html5-qrcode`.
3. **Never edit** `src/lib/api.ts`, `src/lib/errors.ts`, `src/lib/idempotency.ts`, `src/types.ts`
   or `src/config.ts` except where a prompt tells you to. They are provided below and are tested.
   Call them; do not re-implement fetch, headers, retries or error messages anywhere else.
4. Never call `fetch` directly in a component. Use the functions in `api.ts`.
5. Never decide roles from Clerk. The role comes from `GET /me` (`role` field). Hide UI the role
   cannot use, but the server enforces everything.
6. Never store the auth token. Never log it. Never put secrets in the code. (The Clerk publishable
   key and the API URL are public and live in `src/config.ts`.)
7. Mobile first (360 px wide up). No horizontal scrolling. Tap targets at least 44 px. Light and
   dark mode. Accessible: labels on inputs, visible focus, `aria-live` on result banners.
8. Every screen has four states: loading (skeleton), empty (message plus action), error (message
   from `errors.ts` plus Retry button), and content. No blank screens. No raw JSON. No stack traces.
9. Dates: the API returns UTC ISO strings. Show them in the user's local time with the time zone
   name, using `Intl.DateTimeFormat`.
10. Do not invent endpoints, fields or statuses. If something is missing, say so; do not fake data.
11. Keep each change small. Do not refactor files you were not asked to touch.

## 1. Files to create first (verbatim)

### `src/config.ts`
```ts
export const config = {
  apiUrl: "https://entrix-api-zn00.onrender.com",
  clerkPublishableKey: "pk_test_b3JnYW5pYy1jb3lvdGUtMjYzMC5jbGVyay5hY2NvdW50cy5kZXYk",
};
```

### `src/types.ts`
```ts
export type Role = "participant" | "volunteer" | "organizer" | "admin";
export type EventStatus = "draft" | "published" | "closed";
export type Participation = "individual" | "team";
export type RegStatus = "confirmed" | "waitlisted" | "cancelled" | "checked_in";
export type TeamStatus = "forming" | "registered" | "cancelled";

export interface User { id: string; email: string; name: string; college: string | null;
  roll_no: string | null; phone: string | null; role: Role; }
export interface UserPatch { name?: string; college?: string | null; roll_no?: string | null;
  phone?: string | null; }

export interface EventOut { id: string; slug: string; name: string; description: string | null;
  venue: string | null; starts_at: string; ends_at: string; reg_opens_at: string;
  reg_closes_at: string; status: EventStatus; }
export interface Category { id: string; event_id: string; name: string; sport: string;
  participation: Participation; team_size_min: number | null; team_size_max: number | null;
  capacity: number; confirmed_count: number; waitlist_enabled: boolean; seats_left: number; }
export interface EventDetail extends EventOut { categories: Category[]; }
export interface Page<T> { items: T[]; next_cursor: string | null; }

export interface EventCreate { slug: string; name: string; description?: string | null;
  venue?: string | null; starts_at: string; ends_at: string; reg_opens_at: string;
  reg_closes_at: string; }
export type EventPatch = Partial<Omit<EventCreate, "slug">> & { status?: EventStatus };
export interface CategoryCreate { name: string; sport: string; participation: Participation;
  team_size_min?: number | null; team_size_max?: number | null; capacity: number;
  waitlist_enabled?: boolean; }
export type CategoryPatch = Partial<Pick<CategoryCreate,
  "name" | "sport" | "capacity" | "waitlist_enabled">>;

export interface RegistrationResult { registration_id: string; status: RegStatus;
  waitlist_position?: number | null; }
// M6a adds the event/category/team fields to GET /me/registrations.
export interface MyRegistration { registration_id: string; category_id: string; status: RegStatus;
  waitlist_position: number | null; created_at: string; event_id: string; event_name: string;
  event_starts_at: string; venue: string | null; category_name: string; sport: string;
  team_id: string | null; team_name: string | null; }
// M6a: GET /me/teams
export interface MyTeam { id: string; name: string; status: TeamStatus; category_id: string;
  category_name: string; event_id: string; event_name: string; captain_id: string;
  invite_code: string | null; member_count: number; team_size_min: number;
  team_size_max: number; is_captain: boolean; }
export interface TeamMember { user_id: string; name: string; is_captain: boolean; }
export interface TeamOut { id: string; category_id: string; name: string; captain_id: string;
  status: TeamStatus; invite_code: string | null; }
export interface TeamDetail { id: string; category_id: string; name: string; captain_id: string;
  status: TeamStatus; invite_code: string | null; members: TeamMember[]; }

export interface CategoryStats { id: string; name: string; capacity: number; confirmed: number;
  waitlisted: number; checked_in: number; }
export interface EventStats { categories: CategoryStats[]; }
export interface Participant { id: string; name: string; email: string; college: string | null;
  roll_no: string | null; phone: string | null; }
export interface RegistrationRow { registration_id: string; status: RegStatus; category_id: string;
  category_name: string; team_name: string | null; participant: Participant; created_at: string;
  waitlisted_at: string | null; }
export interface CheckInResult { registration_id: string; status: RegStatus;
  already_checked_in: boolean; participant: { name: string; category: string }; }
```

### `src/lib/errors.ts`
```ts
export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string,
              public retryAfter?: number) { super(message); }
}

const MESSAGES: Record<string, string> = {
  unauthenticated: "Please sign in to continue.",
  token_expired: "Your session expired. Please sign in again.",
  invalid_auth_token: "Your session is not valid. Please sign in again.",
  auth_unavailable: "Sign-in is temporarily unavailable. Try again in a minute.",
  forbidden: "You do not have permission to do that.",
  not_found: "We could not find that.",
  validation_error: "Please check the highlighted fields.",
  invalid_cursor: "The list changed. Reload the page.",
  missing_idempotency_key: "Something went wrong on our side. Please try again.",
  idempotency_in_progress: "Still working on your request...",
  already_registered: "You are already registered for this category.",
  category_full: "This category is full.",
  registration_closed: "Registration is not open for this event right now.",
  already_cancelled: "This registration was already cancelled.",
  already_checked_in: "Already checked in.",
  already_in_team: "You are already in a team for this category.",
  not_team_category: "This category is not a team category.",
  team_full: "This team is full.",
  team_cancelled: "This team was cancelled.",
  team_name_taken: "That team name is taken in this category. Choose another.",
  roster_locked: "The team is already registered, so members cannot change.",
  wrong_event: "This QR code belongs to a different event.",
  invalid_token: "That QR code is not valid.",
  slug_taken: "That web address (slug) is already used. Choose another.",
  category_name_taken: "A category with that name already exists in this event.",
  capacity_below_confirmed: "Capacity cannot be lower than the number already confirmed.",
  invalid_status_transition: "That status change is not allowed. Order is draft, published, closed.",
  account_conflict: "This email is linked to a different account. Contact the organizers.",
  rate_limited: "Too many attempts. Please wait a moment.",
  network: "Cannot reach the server. Check your connection.",
  timeout: "The server is taking too long. Please try again.",
  http_error: "Something went wrong. Please try again.",
};

const FALLBACK = "Something went wrong. Please try again.";

export function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 429) {
      return error.retryAfter ? `Too many attempts. Try again in ${error.retryAfter} seconds.`
                              : (MESSAGES["rate_limited"] ?? FALLBACK);
    }
    if (error.code === "validation_error" && error.message) return error.message;
    return MESSAGES[error.code] ?? (error.status >= 500 ? FALLBACK : error.message);
  }
  return FALLBACK;
}
```

### `src/lib/api.ts`
```ts
import { config } from "@/config";
import { ApiError } from "@/lib/errors";
import type * as T from "@/types";

type TokenGetter = (opts?: { skipCache?: boolean }) => Promise<string | null>;
let getToken: TokenGetter = async () => null;
/** Call once from a component under <ClerkProvider>: setTokenGetter(useAuth().getToken). */
export function setTokenGetter(fn: TokenGetter) { getToken = fn; }

/** Listeners are told when a request has been slow, so the UI can show "waking the server". */
type SlowListener = (slow: boolean) => void;
const slowListeners = new Set<SlowListener>();
let slowCount = 0;
export function onServerSlow(fn: SlowListener) { slowListeners.add(fn); return () => { slowListeners.delete(fn); }; }
function setSlow(delta: number) {
  slowCount += delta;
  slowListeners.forEach((l) => l(slowCount > 0));
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

interface Opts {
  body?: unknown;
  idempotencyKey?: string;
  auth?: boolean;         // default true; public GETs send no token
  raw?: boolean;          // return the Response (CSV download)
  signal?: AbortSignal;
}

async function attempt(method: string, path: string, o: Opts, forceFresh: boolean) {
  const headers: Record<string, string> = {};
  if (o.body !== undefined) headers["Content-Type"] = "application/json";
  if (o.idempotencyKey) headers["Idempotency-Key"] = o.idempotencyKey;
  if (o.auth !== false) {
    const token = await getToken(forceFresh ? { skipCache: true } : undefined);
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 70_000);   // a cold start takes about 35 s
  o.signal?.addEventListener("abort", () => ctl.abort());
  try {
    return await fetch(config.apiUrl + path, {
      method, headers, signal: ctl.signal,
      ...(o.body !== undefined ? { body: JSON.stringify(o.body) } : {}),
    });
  } finally { clearTimeout(timer); }
}

async function toError(res: Response): Promise<ApiError> {
  let code = "http_error"; let message = res.statusText;
  try { const j = await res.json(); code = j.error?.code ?? code; message = j.error?.message ?? message; }
  catch { /* non-JSON body (proxy error page) */ }
  const ra = Number(res.headers.get("Retry-After"));
  return new ApiError(res.status, code, message, res.status === 429 && ra > 0 ? ra : undefined);
}

/**
 * Safe-to-repeat requests: GETs, and anything sent with an Idempotency-Key.
 * Retries network failures, 502/503/504 and idempotency_in_progress; refreshes an expired token once.
 */
async function request<R>(method: string, path: string, o: Opts = {}): Promise<R> {
  const repeatable = method === "GET" || !!o.idempotencyKey;
  const maxTries = repeatable ? 6 : 1;
  let refreshed = false;
  let slowTimer: ReturnType<typeof setTimeout> | undefined;
  let marked = false;
  const markSlow = () => { if (!marked) { marked = true; setSlow(1); } };
  slowTimer = setTimeout(markSlow, 4000);
  try {
    for (let i = 0; i < maxTries; i++) {
      let res: Response;
      try {
        res = await attempt(method, path, o, refreshed);
      } catch (e) {
        if (o.signal?.aborted) throw e;
        if (i < maxTries - 1) { await sleep(Math.min(1000 * 2 ** i, 8000)); continue; }
        throw new ApiError(0, (e as Error).name === "AbortError" ? "timeout" : "network",
                           "Cannot reach the server");
      }
      if (res.ok) {
        if (o.raw) return res as unknown as R;
        return (res.status === 204 ? undefined : await res.json()) as R;
      }
      const err = await toError(res);
      if (res.status === 401 && !refreshed && o.auth !== false) { refreshed = true; i--; continue; }
      if (repeatable && i < maxTries - 1 &&
          ([502, 503, 504].includes(res.status) || err.code === "idempotency_in_progress")) {
        await sleep(err.code === "idempotency_in_progress" ? 1000 : Math.min(1000 * 2 ** i, 8000));
        continue;
      }
      throw err;
    }
    throw new ApiError(0, "network", "Cannot reach the server");
  } finally {
    clearTimeout(slowTimer);
    if (marked) setSlow(-1);
  }
}

const qs = (p: Record<string, string | number | undefined | null>) => {
  const s = new URLSearchParams();
  Object.entries(p).forEach(([k, v]) => v != null && v !== "" && s.set(k, String(v)));
  const t = s.toString(); return t ? `?${t}` : "";
};

export const api = {
  // public
  listEvents: (cursor?: string | null) =>
    request<T.Page<T.EventOut>>("GET", `/events${qs({ limit: 20, cursor })}`, { auth: false }),
  getEvent: (id: string) => request<T.EventDetail>("GET", `/events/${id}`, { auth: false }),
  // me
  me: () => request<T.User>("GET", "/me"),
  patchMe: (b: T.UserPatch) => request<T.User>("PATCH", "/me", { body: b }),
  myRegistrations: (cursor?: string | null) =>
    request<T.Page<T.MyRegistration>>("GET", `/me/registrations${qs({ limit: 50, cursor })}`),
  myTeams: () => request<T.MyTeam[]>("GET", "/me/teams"),
  // registration (key comes from idempotency.ts)
  register: (categoryId: string, key: string) =>
    request<T.RegistrationResult>("POST", `/categories/${categoryId}/registrations`, { idempotencyKey: key }),
  registerTeam: (teamId: string, key: string) =>
    request<T.RegistrationResult>("POST", `/teams/${teamId}/register`, { idempotencyKey: key }),
  cancelRegistration: (id: string) => request<T.RegistrationResult>("DELETE", `/registrations/${id}`),
  qr: (id: string) => request<{ token: string }>("GET", `/registrations/${id}/qr`),
  // teams
  createTeam: (categoryId: string, name: string) =>
    request<T.TeamOut>("POST", `/categories/${categoryId}/teams`, { body: { name } }),
  joinTeam: (invite_code: string) => request<T.TeamOut>("POST", "/teams/join", { body: { invite_code } }),
  getTeam: (id: string) => request<T.TeamDetail>("GET", `/teams/${id}`),
  leaveTeam: (id: string) => request<void>("DELETE", `/teams/${id}/members/me`),
  cancelTeam: (id: string) => request<T.TeamOut>("DELETE", `/teams/${id}`),
  // organizer (M6a adds the two organizer event reads)
  orgEvents: () => request<T.EventOut[]>("GET", "/organizer/events"),
  orgEvent: (id: string) => request<T.EventDetail>("GET", `/organizer/events/${id}`),
  createEvent: (b: T.EventCreate) => request<T.EventOut>("POST", "/events", { body: b }),
  patchEvent: (id: string, b: T.EventPatch) => request<T.EventOut>("PATCH", `/events/${id}`, { body: b }),
  createCategory: (eventId: string, b: T.CategoryCreate) =>
    request<T.Category>("POST", `/events/${eventId}/categories`, { body: b }),
  patchCategory: (id: string, b: T.CategoryPatch) =>
    request<T.Category>("PATCH", `/categories/${id}`, { body: b }),
  stats: (eventId: string) => request<T.EventStats>("GET", `/events/${eventId}/stats`),
  registrations: (eventId: string, f: { category_id?: string; status?: string; cursor?: string | null }) =>
    request<T.Page<T.RegistrationRow>>("GET", `/events/${eventId}/registrations${qs({ ...f, limit: 50 })}`),
  /** CSV needs the Authorization header, so a plain link cannot work: fetch it, then save the blob. */
  downloadCsv: async (eventId: string, slug: string) => {
    const res = await request<Response>("GET", `/events/${eventId}/registrations.csv`, { raw: true });
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a"); a.href = url; a.download = `registrations-${slug}.csv`;
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  },
  // volunteer
  checkIn: (eventId: string, token: string) =>
    request<T.CheckInResult>("POST", `/events/${eventId}/check-in`, { body: { token } }),
};
```

### `src/lib/idempotency.ts`
```ts
import { useRef, useState, useCallback } from "react";
import { ApiError } from "@/lib/errors";

/**
 * One in-flight action with a stable Idempotency-Key.
 * - A new key is created per user attempt.
 * - If the call fails in a way where the outcome is unknown (network, timeout, 5xx), the SAME key
 *   is reused when the user taps again, so the server can never register twice.
 * - After a definitive answer (success or a 4xx business error) the key is discarded.
 */
export function useIdempotentAction<R>(run: (key: string) => Promise<R>) {
  const key = useRef<string | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const lock = useRef(false);

  const fire = useCallback(async (): Promise<R | undefined> => {
    if (lock.current) return undefined;              // double tap guard
    lock.current = true; setPending(true); setError(null);
    key.current ??= crypto.randomUUID();
    try {
      const result = await run(key.current);
      key.current = null;
      return result;
    } catch (e) {
      const unknown = !(e instanceof ApiError) || e.status === 0 || e.status >= 500;
      if (!unknown) key.current = null;              // definitive: next tap is a new attempt
      setError(e);
      return undefined;
    } finally { lock.current = false; setPending(false); }
  }, [run]);

  return { fire, pending, error, clearError: () => setError(null) };
}
```

## 2. App wiring (verbatim behaviour)

- `main.tsx`: `<ClerkProvider publishableKey={config.clerkPublishableKey}>` wraps
  `<QueryClientProvider>` wraps `<BrowserRouter>`.
- QueryClient defaults: `retry: false` (api.ts already retries safely), `staleTime: 15_000`,
  `refetchOnWindowFocus: true`.
- A `<AuthBridge/>` component inside ClerkProvider calls `setTokenGetter(useAuth().getToken)`.
- `useMe()` = React Query on `api.me()`, enabled only when signed in. `RequireRole` uses it.
  First sign-in creates the EntriX user automatically on the first authenticated call.
- A global `<ServerWakingBanner/>` uses `onServerSlow`: when true show a slim top banner
  "Waking the server, this can take up to 40 seconds..." with a spinner.
- Use Clerk's `<SignInButton mode="modal">`, `<SignedIn>`, `<SignedOut>`, `<UserButton/>`. Do not
  build custom password forms.
- Error boundary at the root with a friendly page and a Reload button.

## 3. API contract (all JSON; errors are `{"error":{"code","message"}}`)

Base URL `config.apiUrl`. Auth: `Authorization: Bearer <Clerk session token>`.

| Method and path | Who | Notes |
|---|---|---|
| GET `/events?limit&cursor` | public | published events, soonest first, `next_cursor` |
| GET `/events/{id}` | public | event plus `categories[]` with `seats_left` (may lag 3 s) |
| GET / PATCH `/me` | signed in | profile; PATCH accepts name, college, roll_no, phone |
| GET `/me/registrations` | signed in | newest first; rows include event and category names (M6a) |
| GET `/me/teams` | signed in | teams I belong to (M6a) |
| POST `/categories/{id}/registrations` | signed in | needs `Idempotency-Key`; 201 with `status` confirmed or waitlisted |
| DELETE `/registrations/{id}` | owner | cancels; a waitlisted person may be promoted by the server |
| GET `/registrations/{id}/qr` | owner | `{token}`; the QR image encodes exactly this string |
| POST `/categories/{id}/teams` | signed in | `{name}` creates a team; the caller is captain and gets `invite_code` |
| POST `/teams/join` | signed in | `{invite_code}` (upper-case it) |
| GET `/teams/{id}` | member | members; `invite_code` only for the captain |
| DELETE `/teams/{id}/members/me` | member | leave (not the captain, not after registration) |
| POST `/teams/{id}/register` | captain | needs `Idempotency-Key`; team size must be within min and max |
| DELETE `/teams/{id}` | captain | cancel team |
| GET `/organizer/events`, `/organizer/events/{id}` | organizer | all statuses including draft (M6a) |
| POST `/events`, PATCH `/events/{id}` | organizer | status order draft, published, closed; the server rejects other moves |
| POST `/events/{id}/categories`, PATCH `/categories/{id}` | organizer | capacity cannot go below confirmed; raising it promotes the waitlist |
| GET `/events/{id}/stats` | organizer | per category capacity, confirmed, waitlisted, checked_in |
| GET `/events/{id}/registrations` | organizer | filters `category_id`, `status`, cursor |
| GET `/events/{id}/registrations.csv` | organizer | download with `api.downloadCsv` |
| POST `/events/{id}/check-in` | volunteer, organizer | `{token}`; 200 with `already_checked_in` true or false |

Roles: `participant` (default), `volunteer`, `organizer`, `admin`. Organizer and admin can do
everything a volunteer can.

Rules the UI must respect:
- Registration is open when `now >= reg_opens_at` and `now < reg_closes_at` and the event is
  `published`. Compute this only to enable or label buttons; the server decides.
- Team categories have no "Register" button; they have "Create team" and "Join with code".
- A team registers as a whole; only the captain sees "Register team", enabled when
  `member_count >= team_size_min`.
- Waitlist: a category with `seats_left == 0` and `waitlist_enabled` shows "Join waitlist".
  With waitlist disabled it shows "Full" and no button.

## 4. Design

Clean, modern, friendly sports feel. One accent colour (a confident blue or green; pick one and use
design tokens, no hard-coded hex in components). Rounded cards, generous spacing, large readable
type. Status badges: confirmed green, waitlisted amber, cancelled grey, checked_in blue.
Logo text "EntriX". Use lucide-react icons. Empty states have an icon and a helpful sentence.

## 5. Definition of done for any screen

Loading, empty, error and content states exist; works at 360 px; no console errors; every button
that calls the API is disabled while pending; every error shows `messageFor(error)` in a toast or
inline alert; no new dependency beyond the three allowed.
