import type { Category, EventOut } from "@/types";

/** Local date and time, with the time zone name, from a UTC ISO string. */
export function formatDateTime(iso: string): string {
  // dateStyle/timeStyle cannot be combined with timeZoneName (browsers throw), so spell it out.
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(new Date(iso));
}

export function formatDate(iso: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(iso));
}

export function formatDateRange(startIso: string, endIso: string): string {
  const a = formatDate(startIso);
  const b = formatDate(endIso);
  return a === b ? a : `${a} to ${b}`;
}

export type RegWindow = "upcoming" | "open" | "closed";

/**
 * Whether registration is open. Only used to label and enable buttons: the server always has the
 * last word (a visitor's clock can be wrong), so a mismatch just shows the server's message.
 */
export function registrationWindow(
  event: Pick<EventOut, "status" | "reg_opens_at" | "reg_closes_at">,
  now: number = Date.now(),
): RegWindow {
  if (event.status !== "published") return "closed";
  if (now < new Date(event.reg_opens_at).getTime()) return "upcoming";
  if (now >= new Date(event.reg_closes_at).getTime()) return "closed";
  return "open";
}

export type CategoryAction =
  | "register"
  | "waitlist"
  | "full"
  | "team"
  | "not_open_yet"
  | "closed";

/** What the card offers. Team categories never show a plain Register button. */
export function categoryAction(
  category: Pick<Category, "participation" | "seats_left" | "waitlist_enabled">,
  window: RegWindow,
): CategoryAction {
  if (window === "upcoming") return "not_open_yet";
  if (window === "closed") return "closed";
  if (category.participation === "team") return "team";
  if (category.seats_left > 0) return "register";
  return category.waitlist_enabled ? "waitlist" : "full";
}

export function seatsLabel(category: Pick<Category, "seats_left" | "capacity">): string {
  return `${Math.max(category.seats_left, 0)} of ${category.capacity} seats left`;
}
