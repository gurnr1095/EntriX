import type { EventStatus } from "@/types";

/** "Zeal Sports Fest 2026" becomes "zeal-sports-fest-2026" (the API accepts a-z, 0-9 and single hyphens). */
export function slugify(name: string): string {
  return name
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export const SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

const pad = (n: number) => String(n).padStart(2, "0");

/** An ISO instant to the "YYYY-MM-DDTHH:mm" value a datetime-local input wants, in local time. */
export function isoToLocal(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** A datetime-local value (local time) to a UTC ISO string for the API. */
export function localToIso(local: string): string {
  return new Date(local).toISOString();
}

export interface EventTimes { starts: string; ends: string; opens: string; closes: string; }

/** Mirrors the server's rules so people see the problem before sending. Returns a message or null. */
export function validateEventTimes(t: EventTimes): string | null {
  const ms = (v: string) => new Date(v).getTime();
  const all = [t.starts, t.ends, t.opens, t.closes];
  if (all.some((v) => !v || Number.isNaN(ms(v)))) return "Fill in all four dates and times.";
  if (!(ms(t.starts) < ms(t.ends))) return "The event must start before it ends.";
  if (!(ms(t.opens) < ms(t.closes))) return "Registration must open before it closes.";
  if (!(ms(t.closes) <= ms(t.ends))) return "Registration must close before the event ends.";
  return null;
}

const NEXT: Partial<Record<EventStatus, EventStatus>> = { draft: "published", published: "closed" };

export function nextStatus(status: EventStatus): EventStatus | null {
  return NEXT[status] ?? null;
}

export function nextStatusLabel(status: EventStatus): string | null {
  return status === "draft" ? "Publish event" : status === "published" ? "Close event" : null;
}

export function nextStatusWarning(status: EventStatus): string {
  return status === "draft"
    ? "Publishing makes the event visible to everyone. Registration opens at the time you set."
    : "Closing hides the event from the public list and stops new registrations. This cannot be undone.";
}

export interface CategoryValues {
  name: string;
  sport: string;
  participation: "individual" | "team";
  teamMin: string;
  teamMax: string;
  capacity: string;
}

/** Mirrors the server's category rules. Returns a message or null. */
export function validateCategory(v: CategoryValues): string | null {
  if (!v.name.trim()) return "Give the category a name.";
  if (!v.sport.trim()) return "Enter the sport.";
  const cap = Number(v.capacity);
  if (!Number.isInteger(cap) || cap < 1) return "Capacity must be a whole number of at least 1.";
  if (v.participation === "team") {
    const min = Number(v.teamMin);
    const max = Number(v.teamMax);
    if (!Number.isInteger(min) || !Number.isInteger(max) || min < 1) return "Set the team size, at least 1 player.";
    if (max < min) return "The largest team cannot be smaller than the smallest.";
  }
  return null;
}
