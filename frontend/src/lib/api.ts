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
  /** Only allowed while nobody has registered; the server answers 409 event_has_registrations otherwise. */
  deleteEvent: (id: string) => request<void>("DELETE", `/events/${id}`),
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
