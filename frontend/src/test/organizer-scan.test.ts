import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/errors";
import { isoToLocal, localToIso, nextStatus, nextStatusLabel, SLUG_PATTERN, slugify, validateEventTimes } from "@/lib/organizer";
import { describeCameraError, extractToken, outcomeFromError, outcomeFromResult, scanLink, ScanGate, tokenFromHash } from "@/lib/scan";

describe("slugify", () => {
  it("makes API-valid slugs", () => {
    for (const name of ["Zeal Sports Fest 2026", "  Cafe  Cup!! ", "A--B", "Winter Cup (Badminton) 3.0"]) {
      expect(slugify(name)).toMatch(SLUG_PATTERN);
    }
    expect(slugify("Zeal Sports Fest 2026")).toBe("zeal-sports-fest-2026");
    expect(slugify("Café Cup")).toBe("cafe-cup");
    expect(slugify("!!!")).toBe("");
  });
});

describe("local time conversion", () => {
  it("round-trips a datetime-local value", () => {
    expect(isoToLocal(localToIso("2030-03-04T09:30"))).toBe("2030-03-04T09:30");
  });
  it("produces a UTC ISO instant", () => {
    expect(localToIso("2030-03-04T09:30")).toMatch(/Z$/);
  });
});

describe("validateEventTimes", () => {
  const ok = { starts: "2030-05-02T09:00", ends: "2030-05-03T18:00", opens: "2030-04-01T09:00", closes: "2030-05-01T09:00" };
  it("accepts a valid schedule, including closing exactly when the event ends", () => {
    expect(validateEventTimes(ok)).toBeNull();
    expect(validateEventTimes({ ...ok, closes: ok.ends })).toBeNull();
  });
  it("matches each server rule", () => {
    expect(validateEventTimes({ ...ok, ends: "2030-05-02T08:00" })).toMatch(/start before it ends/);
    expect(validateEventTimes({ ...ok, closes: "2030-03-01T09:00" })).toMatch(/open before it closes/);
    expect(validateEventTimes({ ...ok, closes: "2030-05-04T09:00" })).toMatch(/close before the event ends/);
    expect(validateEventTimes({ ...ok, opens: "" })).toMatch(/all four/);
  });
});

describe("status steps", () => {
  it("only moves forward, one step at a time", () => {
    expect(nextStatus("draft")).toBe("published");
    expect(nextStatus("published")).toBe("closed");
    expect(nextStatus("closed")).toBeNull();
    expect(nextStatusLabel("closed")).toBeNull();
  });
});

describe("scan outcomes", () => {
  const result = (already: boolean) => ({
    registration_id: "r", status: "checked_in" as const, already_checked_in: already,
    participant: { name: "Asha", category: "Chess" },
  });
  it("is green the first time and amber the second", () => {
    expect(outcomeFromResult(result(false)).tone).toBe("success");
    expect(outcomeFromResult(result(true)).tone).toBe("already");
    expect(outcomeFromResult(result(true)).detail).toContain("Asha");
  });
  it("explains errors in words", () => {
    expect(outcomeFromError(new ApiError(409, "wrong_event", "x")).detail).toMatch(/different event/);
    expect(outcomeFromError(new ApiError(400, "invalid_token", "x")).detail).toMatch(/not valid/);
    expect(outcomeFromError(new ApiError(409, "not_confirmed", "x")).detail).toMatch(/cancelled or on the waitlist/);
    expect(outcomeFromError(new ApiError(0, "network", "x")).title).toBe("No connection");
  });
});

describe("ScanGate", () => {
  it("ignores the same code inside the window, accepts it after, and never overlaps requests", () => {
    let t = 0;
    const gate = new ScanGate(3000, () => t);
    expect(gate.begin("A")).toBe(true);
    expect(gate.begin("B")).toBe(false); // a request is still in flight
    gate.done();
    t = 1000;
    expect(gate.begin("A")).toBe(false); // same code, too soon
    expect(gate.begin("B")).toBe(true); // a different code is fine
    gate.done();
    t = 5000;
    expect(gate.begin("A")).toBe(true); // window passed
    gate.done();
    expect(gate.begin("   ")).toBe(false);
  });
});

import { validateCategory, type CategoryValues } from "@/lib/organizer";

describe("validateCategory", () => {
  const base: CategoryValues = { name: "Chess", sport: "chess", participation: "individual", teamMin: "", teamMax: "", capacity: "16" };
  it("accepts a good individual and a good team category", () => {
    expect(validateCategory(base)).toBeNull();
    expect(validateCategory({ ...base, participation: "team", teamMin: "2", teamMax: "4" })).toBeNull();
  });
  it("catches each problem before the server does", () => {
    expect(validateCategory({ ...base, name: " " })).toMatch(/name/);
    expect(validateCategory({ ...base, capacity: "0" })).toMatch(/Capacity/);
    expect(validateCategory({ ...base, capacity: "2.5" })).toMatch(/whole number/);
    expect(validateCategory({ ...base, participation: "team", teamMin: "", teamMax: "" })).toMatch(/team size/);
    expect(validateCategory({ ...base, participation: "team", teamMin: "5", teamMax: "3" })).toMatch(/cannot be smaller/);
  });
  it("ignores team sizes for individual categories", () => {
    expect(validateCategory({ ...base, teamMin: "9", teamMax: "1" })).toBeNull();
  });
});

describe("describeCameraError", () => {
  it("explains the common camera failures", () => {
    expect(describeCameraError(Object.assign(new Error("Permission denied"), { name: "NotAllowedError" }))).toMatch(/blocked/);
    expect(describeCameraError("Error getting userMedia, error = NotAllowedError: Permission dismissed")).toMatch(/blocked/);
    expect(describeCameraError(Object.assign(new Error("x"), { name: "NotFoundError" }))).toMatch(/No camera/);
    expect(describeCameraError(Object.assign(new Error("x"), { name: "NotReadableError" }))).toMatch(/Another app/);
    expect(describeCameraError(Object.assign(new Error("x"), { name: "OverconstrainedError" }))).toMatch(/Switch camera/);
    expect(describeCameraError(new Error("weird"))).toBe("The camera could not start.");
  });
});

describe("scan links", () => {
  const token = "5b2f8c1e-0000-4000-8000-123456789abc.AbC_dEf-123";
  it("round-trips a token through the link the QR shows", () => {
    const link = scanLink("https://entri-x.vercel.app", token);
    expect(link).toBe("https://entri-x.vercel.app/scan#t=" + encodeURIComponent(token));
    expect(extractToken(link)).toBe(token);
    expect(tokenFromHash(new URL(link).hash)).toBe(token);
  });
  it("still accepts a bare token (older QR codes and emails)", () => {
    expect(extractToken("  " + token + " ")).toBe(token);
  });
  it("accepts a ?t= link and leaves other text alone", () => {
    expect(extractToken("https://example.com/scan?t=" + token)).toBe(token);
    expect(extractToken("https://example.com/other")).toBe("https://example.com/other");
    expect(extractToken("hello world")).toBe("hello world");
    expect(tokenFromHash("#nothing=here")).toBeNull();
    expect(tokenFromHash("")).toBeNull();
  });
});
