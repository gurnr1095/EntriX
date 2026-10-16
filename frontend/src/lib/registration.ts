import type { RegStatus } from "@/types";

/** What a participant may do with a registration, by status. The server enforces it too. */
export function registrationActions(status: RegStatus) {
  return {
    canShowQr: status === "confirmed" || status === "checked_in",
    canCancel: status === "confirmed" || status === "waitlisted",
  };
}

/** Turn "" into null for optional profile fields; keep real text trimmed. */
export function blankToNull(value: string): string | null {
  const v = value.trim();
  return v === "" ? null : v;
}
