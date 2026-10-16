import type { MyTeam } from "@/types";

/** What the signed-in person may do with a team. The server enforces every rule again. */
export function teamActions(t: Pick<MyTeam, "status" | "is_captain" | "member_count" | "team_size_min" | "team_size_max">) {
  const forming = t.status === "forming";
  const needed = Math.max(0, t.team_size_min - t.member_count);
  const tooMany = t.member_count > t.team_size_max;
  const canRegister = t.is_captain && forming && needed === 0 && !tooMany;
  let registerHint: string | null = null;
  if (t.is_captain && forming) {
    if (needed > 0) registerHint = `Needs ${needed} more ${needed === 1 ? "player" : "players"} before you can register.`;
    else if (tooMany) registerHint = "The team is over its size limit.";
  }
  return {
    canRegister,
    registerHint,
    // The captain cannot simply walk away from the team: they cancel it instead.
    canLeave: !t.is_captain && forming,
    canCancel: t.is_captain && t.status !== "cancelled",
    full: t.member_count >= t.team_size_max,
  };
}

export function teamStatusLabel(status: MyTeam["status"]): string {
  return status === "forming" ? "Forming" : status === "registered" ? "Registered" : "Cancelled";
}
