import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setTokenGetter } from "@/lib/api";
import { ApiError, messageFor } from "@/lib/errors";

const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
const err = (status: number, code: string, headers?: Record<string, string>) =>
  json(status, { error: { code, message: code } }, headers);

let calls: { url: string; init: RequestInit }[];
let script: Array<Response | Error>;

beforeEach(() => {
  vi.useFakeTimers();
  calls = [];
  script = [];
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    const next = script.shift();
    if (!next) throw new Error("unexpected extra request");
    if (next instanceof Error) throw next;
    return next;
  });
  setTokenGetter(async (o) => (o?.skipCache ? "fresh" : "stale"));
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

const run = async <T,>(p: Promise<T>) => { const settled = p.then((v) => v, (e) => e); await vi.runAllTimersAsync(); return settled; };
const header = (i: number, name: string) => (calls[i]?.init.headers as Record<string, string>)[name];

describe("api client", () => {
  it("retries a GET that failed on the network, then succeeds (cold start)", async () => {
    script = [new TypeError("failed"), new TypeError("failed"), json(200, { items: [], next_cursor: null })];
    expect(await run(api.listEvents())).toEqual({ items: [], next_cursor: null });
    expect(calls).toHaveLength(3);
  });

  it("public reads send no token", async () => {
    script = [json(200, { items: [], next_cursor: null })];
    await run(api.listEvents());
    expect(header(0, "Authorization")).toBeUndefined();
  });

  it("resends a registration with the SAME idempotency key after a 503", async () => {
    script = [err(503, "http_error"), json(201, { registration_id: "r1", status: "confirmed" })];
    const result = await run(api.register("c1", "key-1"));
    expect(result).toMatchObject({ status: "confirmed" });
    expect(calls.map((_, i) => header(i, "Idempotency-Key"))).toEqual(["key-1", "key-1"]);
  });

  it("waits and resends the same key on idempotency_in_progress", async () => {
    script = [err(409, "idempotency_in_progress"), json(201, { registration_id: "r1", status: "waitlisted" })];
    expect(await run(api.register("c1", "key-2"))).toMatchObject({ status: "waitlisted" });
    expect(calls).toHaveLength(2);
  });

  it("never retries a business error", async () => {
    script = [err(409, "category_full")];
    const e = await run(api.register("c1", "k"));
    expect(e).toBeInstanceOf(ApiError);
    expect((e as ApiError).code).toBe("category_full");
    expect(calls).toHaveLength(1);
  });

  it("does not retry a POST that has no idempotency key", async () => {
    script = [new TypeError("failed")];
    const e = await run(api.createTeam("c1", "Lions"));
    expect((e as ApiError).code).toBe("network");
    expect(calls).toHaveLength(1);
  });

  it("refreshes an expired token once, with a fresh token", async () => {
    script = [err(401, "token_expired"), json(200, { id: "u1" })];
    expect(await run(api.me())).toEqual({ id: "u1" });
    expect(header(0, "Authorization")).toBe("Bearer stale");
    expect(header(1, "Authorization")).toBe("Bearer fresh");
  });

  it("gives up after the one refresh", async () => {
    script = [err(401, "token_expired"), err(401, "token_expired")];
    expect(((await run(api.me())) as ApiError).status).toBe(401);
    expect(calls).toHaveLength(2);
  });

  it("surfaces Retry-After on a 429", async () => {
    script = [err(429, "rate_limited", { "Retry-After": "17" })];
    const e = (await run(api.register("c1", "k"))) as ApiError;
    expect(e.retryAfter).toBe(17);
    expect(messageFor(e)).toContain("17 seconds");
  });

  it("copes with a non-JSON error page from a proxy", async () => {
    script = [new Response("<html>bad gateway</html>", { status: 502 }), json(200, { ok: 1 })];
    expect(await run(api.getEvent("e1"))).toEqual({ ok: 1 });
  });

  it("gives up after the retry budget and reports a network error", async () => {
    script = Array.from({ length: 6 }, () => new TypeError("failed"));
    expect(((await run(api.getEvent("e1"))) as ApiError).code).toBe("network");
    expect(calls).toHaveLength(6);
  });
});

describe("messages", () => {
  it("never shows raw codes or JSON for known errors", () => {
    for (const code of ["already_registered", "category_full", "registration_closed", "team_full", "invalid_token", "wrong_event"]) {
      const m = messageFor(new ApiError(409, code, "raw server text"));
      expect(m).not.toContain("raw server text");
      expect(m).not.toContain("_");
    }
  });
  it("is safe for unknown things", () => {
    expect(messageFor(new Error("boom"))).toMatch(/something went wrong/i);
    expect(messageFor(new ApiError(500, "weird", "x"))).toMatch(/something went wrong/i);
  });
});
