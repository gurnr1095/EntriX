import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QrDialog } from "@/components/qr-dialog";
import { api } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import { clearCachedQr, getCachedQr, setCachedQr } from "@/lib/qr-cache";
import { blankToNull, registrationActions } from "@/lib/registration";
import type { MyRegistration } from "@/types";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("registrationActions", () => {
  it("shows the QR only for confirmed and checked-in, and cancel only before the event", () => {
    expect(registrationActions("confirmed")).toEqual({ canShowQr: true, canCancel: true });
    expect(registrationActions("waitlisted")).toEqual({ canShowQr: false, canCancel: true });
    expect(registrationActions("checked_in")).toEqual({ canShowQr: true, canCancel: false });
    expect(registrationActions("cancelled")).toEqual({ canShowQr: false, canCancel: false });
  });
  it("turns blank optional fields into null", () => {
    expect(blankToNull("  ")).toBeNull();
    expect(blankToNull(" 22CS101 ")).toBe("22CS101");
  });
});

describe("qr cache", () => {
  beforeEach(() => localStorage.clear());
  it("round-trips and clears", () => {
    expect(getCachedQr("r1")).toBeNull();
    setCachedQr("r1", "tok");
    expect(getCachedQr("r1")).toBe("tok");
    clearCachedQr("r1");
    expect(getCachedQr("r1")).toBeNull();
  });
  it("survives storage that throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    expect(getCachedQr("r1")).toBeNull();
    expect(() => setCachedQr("r1", "x")).not.toThrow();
    vi.restoreAllMocks();
  });
});

const reg = (over: Partial<MyRegistration> = {}): MyRegistration => ({
  registration_id: "r1", category_id: "c1", status: "confirmed", waitlist_position: null,
  created_at: "2030-01-01T00:00:00Z", event_id: "e1", event_name: "Zeal", event_starts_at: "2030-02-01T00:00:00Z",
  venue: null, category_name: "Singles", sport: "chess", team_id: null, team_name: null, ...over,
});

async function mount(r: MyRegistration) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<QrDialog registration={r} participantName="Asha" onClose={() => {}} />); });
  await act(async () => { await Promise.resolve(); });
  return () => act(() => root.unmount());
}

describe("QrDialog", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => { document.body.innerHTML = ""; vi.restoreAllMocks(); });

  it("draws the token from the server and caches it", async () => {
    vi.spyOn(api, "qr").mockResolvedValue({ token: "abc.def" });
    const unmount = await mount(reg());
    expect(document.body.querySelector("svg title")?.textContent).toBe("Check-in QR code");
    expect(getCachedQr("r1")).toBe("abc.def");
    await unmount();
  });

  it("still shows the saved code when offline, and says so", async () => {
    setCachedQr("r1", "saved.token");
    vi.spyOn(api, "qr").mockRejectedValue(new ApiError(0, "network", "x"));
    const unmount = await mount(reg());
    expect(document.body.querySelector("svg")).not.toBeNull();
    expect(document.body.textContent).toContain("Showing your saved code");
    await unmount();
  });

  it("shows a message, not a broken image, when there is no code at all", async () => {
    vi.spyOn(api, "qr").mockRejectedValue(new ApiError(0, "network", "x"));
    const unmount = await mount(reg());
    expect(document.body.querySelector("svg title")).toBeNull();
    expect(document.body.textContent).toMatch(/cannot reach the server/i);
    await unmount();
  });

  it("marks a checked-in registration", async () => {
    vi.spyOn(api, "qr").mockResolvedValue({ token: "t" });
    const unmount = await mount(reg({ status: "checked_in" }));
    expect(document.body.textContent).toContain("Checked in");
    await unmount();
  });
});
