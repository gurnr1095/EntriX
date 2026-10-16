import { describe, expect, it } from "vitest";
import { categoryAction, formatDate, formatDateRange, formatDateTime, registrationWindow, seatsLabel } from "@/lib/format";

const event = (over: Partial<Parameters<typeof registrationWindow>[0]> = {}) => ({
  status: "published" as const,
  reg_opens_at: "2030-01-10T10:00:00Z",
  reg_closes_at: "2030-01-20T10:00:00Z",
  ...over,
});
const at = (iso: string) => new Date(iso).getTime();

describe("registrationWindow", () => {
  it("is upcoming, open, then closed", () => {
    expect(registrationWindow(event(), at("2030-01-09T00:00:00Z"))).toBe("upcoming");
    expect(registrationWindow(event(), at("2030-01-10T10:00:00Z"))).toBe("open"); // opens inclusive
    expect(registrationWindow(event(), at("2030-01-15T00:00:00Z"))).toBe("open");
    expect(registrationWindow(event(), at("2030-01-20T10:00:00Z"))).toBe("closed"); // closes exclusive
  });
  it("is closed whenever the event is not published", () => {
    expect(registrationWindow(event({ status: "closed" }), at("2030-01-15T00:00:00Z"))).toBe("closed");
    expect(registrationWindow(event({ status: "draft" }), at("2030-01-15T00:00:00Z"))).toBe("closed");
  });
});

describe("categoryAction", () => {
  const ind = (seats_left: number, waitlist_enabled = true) => ({ participation: "individual" as const, seats_left, waitlist_enabled });
  it("offers Register, then waitlist, then Full", () => {
    expect(categoryAction(ind(3), "open")).toBe("register");
    expect(categoryAction(ind(0), "open")).toBe("waitlist");
    expect(categoryAction(ind(0, false), "open")).toBe("full");
  });
  it("team categories never show a plain Register button", () => {
    expect(categoryAction({ participation: "team", seats_left: 5, waitlist_enabled: true }, "open")).toBe("team");
    expect(categoryAction({ participation: "team", seats_left: 0, waitlist_enabled: false }, "open")).toBe("team");
  });
  it("nothing is offered outside the window", () => {
    expect(categoryAction(ind(3), "upcoming")).toBe("not_open_yet");
    expect(categoryAction(ind(3), "closed")).toBe("closed");
    expect(categoryAction({ participation: "team", seats_left: 3, waitlist_enabled: true }, "closed")).toBe("closed");
  });
});

describe("seatsLabel", () => {
  it("never shows negative seats", () => {
    expect(seatsLabel({ seats_left: -1, capacity: 5 })).toBe("0 of 5 seats left");
    expect(seatsLabel({ seats_left: 3, capacity: 5 })).toBe("3 of 5 seats left");
  });
});

describe("date formatting", () => {
  // These once threw in the browser (dateStyle combined with timeZoneName) and blanked every event page.
  it("formats without throwing and includes the time zone", () => {
    const text = formatDateTime("2030-01-10T10:00:00Z");
    expect(text).toMatch(/2030/);
    expect(text).toMatch(/[A-Z]{2,5}|GMT|UTC/); // a zone name such as IST, UTC or GMT+5:30
  });
  it("collapses a same-day range", () => {
    expect(formatDateRange("2030-01-10T10:00:00Z", "2030-01-10T12:00:00Z")).toBe(formatDate("2030-01-10T10:00:00Z"));
    expect(formatDateRange("2030-01-10T10:00:00Z", "2030-01-12T12:00:00Z")).toContain(" to ");
  });
});
