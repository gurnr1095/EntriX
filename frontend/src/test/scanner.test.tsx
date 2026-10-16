import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QrScanner } from "@/components/qr-scanner";
import { api } from "@/lib/api";
import { ApiError } from "@/lib/errors";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;

beforeEach(async () => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<QrScanner eventId="e1" />); });
  await act(async () => { await new Promise((r) => setTimeout(r, 30)); }); // let the camera attempt fail in jsdom
});
afterEach(() => { act(() => root.unmount()); document.body.innerHTML = ""; vi.restoreAllMocks(); });

async function typeAndSubmit(text: string) {
  const input = host.querySelector<HTMLInputElement>("#manual-token")!;
  await act(async () => {
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    set.call(input, text);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => { host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
  await act(async () => { await Promise.resolve(); });
}

const result = (already: boolean) => ({
  registration_id: "r1", status: "checked_in" as const, already_checked_in: already,
  participant: { name: "Asha Rao", category: "Chess Open" },
});

describe("QrScanner", () => {
  it("falls back to manual entry when there is no camera", () => {
    expect(host.textContent).toContain("camera is not available");
    expect(host.querySelector("#manual-token")).not.toBeNull();
  });

  it("checks in with the chosen event and shows who was checked in", async () => {
    const spy = vi.spyOn(api, "checkIn").mockResolvedValue(result(false));
    await typeAndSubmit("  reg.token  ");
    expect(spy).toHaveBeenCalledWith("e1", "reg.token");
    expect(host.textContent).toContain("Checked in");
    expect(host.textContent).toContain("Asha Rao");
    expect(host.textContent).toContain("Checked in this session: 1");
  });

  it("does not count a repeat scan and says so", async () => {
    vi.spyOn(api, "checkIn").mockResolvedValue(result(true));
    await typeAndSubmit("another.token");
    expect(host.textContent).toContain("Already checked in");
    expect(host.textContent).toContain("Checked in this session: 0");
  });

  it("shows a clear error for a wrong-event code", async () => {
    vi.spyOn(api, "checkIn").mockRejectedValue(new ApiError(409, "wrong_event", "x"));
    await typeAndSubmit("other.event.token");
    expect(host.textContent).toContain("Cannot check in");
    expect(host.textContent).toMatch(/different event/);
  });

  it("tells the volunteer when the network is down", async () => {
    vi.spyOn(api, "checkIn").mockRejectedValue(new ApiError(0, "network", "x"));
    await typeAndSubmit("any.token.here");
    expect(host.textContent).toContain("No connection");
    expect(host.textContent).toContain("Nothing was recorded");
  });
});

describe("QrScanner opened from a scan link", () => {
  it("checks in the token from the link once, then reports it used", async () => {
    const spy = vi.spyOn(api, "checkIn").mockResolvedValue(result(false));
    const used = vi.fn();
    await act(async () => { root.render(<QrScanner eventId="e1" initialToken="tok.from.link" onInitialTokenUsed={used} />); });
    await act(async () => { await new Promise((r) => setTimeout(r, 30)); });
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith("e1", "tok.from.link");
    expect(used).toHaveBeenCalledTimes(1);
    expect(host.textContent).toContain("Asha Rao");
  });

  it("accepts a whole scan link typed or pasted by hand", async () => {
    const spy = vi.spyOn(api, "checkIn").mockResolvedValue(result(false));
    await typeAndSubmit("https://entri-x.vercel.app/scan#t=abc.def");
    expect(spy).toHaveBeenCalledWith("e1", "abc.def");
  });
});
