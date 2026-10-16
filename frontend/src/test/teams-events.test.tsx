import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EventForm, type EventFormValues } from "@/components/event-form";
import { teamActions, teamStatusLabel } from "@/lib/teams";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const team = (over: Partial<Parameters<typeof teamActions>[0]> = {}) => ({
  status: "forming" as const, is_captain: true, member_count: 3, team_size_min: 3, team_size_max: 5, ...over,
});

describe("teamActions", () => {
  it("lets the captain register only once the team is big enough", () => {
    expect(teamActions(team()).canRegister).toBe(true);
    const small = teamActions(team({ member_count: 1 }));
    expect(small.canRegister).toBe(false);
    expect(small.registerHint).toBe("Needs 2 more players before you can register.");
    expect(teamActions(team({ member_count: 2 })).registerHint).toBe("Needs 1 more player before you can register.");
    expect(teamActions(team({ member_count: 6 })).canRegister).toBe(false);
  });
  it("never offers registration to a non-captain or after the team is registered", () => {
    expect(teamActions(team({ is_captain: false })).canRegister).toBe(false);
    expect(teamActions(team({ status: "registered" })).canRegister).toBe(false);
    expect(teamActions(team({ status: "cancelled" })).canRegister).toBe(false);
  });
  it("captains cancel, members leave, and nobody leaves a locked roster", () => {
    expect(teamActions(team()).canLeave).toBe(false);
    expect(teamActions(team()).canCancel).toBe(true);
    expect(teamActions(team({ is_captain: false })).canLeave).toBe(true);
    expect(teamActions(team({ is_captain: false })).canCancel).toBe(false);
    expect(teamActions(team({ is_captain: false, status: "registered" })).canLeave).toBe(false);
    expect(teamActions(team({ status: "cancelled" })).canCancel).toBe(false);
  });
  it("labels statuses", () => {
    expect(teamStatusLabel("forming")).toBe("Forming");
    expect(teamStatusLabel("registered")).toBe("Registered");
  });
});

let root: Root;
let host: HTMLDivElement;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); document.body.innerHTML = ""; });

async function fill(id: string, value: string) {
  const el = host.querySelector<HTMLInputElement | HTMLTextAreaElement>(`#${id}`)!;
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  await act(async () => {
    Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function submit() {
  await act(async () => { host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
  await act(async () => { await Promise.resolve(); });
}

describe("EventForm", () => {
  async function mount(onSubmit: (v: EventFormValues) => Promise<void>) {
    await act(async () => { root.render(<EventForm mode="create" submitLabel="Create event" onSubmit={onSubmit} />); });
  }
  const dates = async (s: string, e: string, o: string, c: string) => {
    await fill("ev-starts", s); await fill("ev-ends", e); await fill("ev-opens", o); await fill("ev-closes", c);
  };

  it("fills the web address from the name until it is edited by hand", async () => {
    await mount(vi.fn());
    await fill("ev-name", "Zeal Sports Fest 2026");
    expect(host.querySelector<HTMLInputElement>("#ev-slug")!.value).toBe("zeal-sports-fest-2026");
    await fill("ev-slug", "custom-slug");
    await fill("ev-name", "Something Else");
    expect(host.querySelector<HTMLInputElement>("#ev-slug")!.value).toBe("custom-slug");
  });

  it("refuses an impossible schedule without calling the server", async () => {
    const onSubmit = vi.fn(async () => {});
    await mount(onSubmit);
    await fill("ev-name", "Cup");
    await dates("2030-05-03T09:00", "2030-05-02T09:00", "2030-04-01T09:00", "2030-05-01T09:00");
    await submit();
    expect(onSubmit).not.toHaveBeenCalled();
    expect(host.querySelector("[role=alert]")?.textContent).toMatch(/start before it ends/);
  });

  it("sends UTC times and turns blank optional fields into null", async () => {
    const onSubmit = vi.fn(async () => {});
    await mount(onSubmit);
    await fill("ev-name", "Cup");
    await dates("2030-05-02T09:00", "2030-05-03T18:00", "2030-04-01T09:00", "2030-05-01T09:00");
    await submit();
    expect(onSubmit).toHaveBeenCalledTimes(1);
    const v = (onSubmit.mock.calls[0] as unknown as [EventFormValues])[0];
    expect(v).toMatchObject({ slug: "cup", name: "Cup", description: null, venue: null });
    expect(v.starts_at).toMatch(/Z$/);
    expect(new Date(v.reg_closes_at).getTime()).toBeLessThan(new Date(v.starts_at).getTime());
  });

  it("shows the server's reason in words when saving fails", async () => {
    const { ApiError } = await import("@/lib/errors");
    const onSubmit = vi.fn(async () => { throw new ApiError(409, "slug_taken", "x"); });
    await mount(onSubmit);
    await fill("ev-name", "Cup");
    await dates("2030-05-02T09:00", "2030-05-03T18:00", "2030-04-01T09:00", "2030-05-01T09:00");
    await submit();
    expect(host.querySelector("[role=alert]")?.textContent).toMatch(/already used/);
  });
});
