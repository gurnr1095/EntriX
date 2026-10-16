import { ApiError, messageFor } from "@/lib/errors";
import type { CheckInResult } from "@/types";

export type ScanTone = "success" | "already" | "error";
export interface ScanOutcome { tone: ScanTone; title: string; detail: string; }

export function outcomeFromResult(r: CheckInResult): ScanOutcome {
  return r.already_checked_in
    ? { tone: "already", title: "Already checked in", detail: `${r.participant.name} · ${r.participant.category}` }
    : { tone: "success", title: "Checked in", detail: `${r.participant.name} · ${r.participant.category}` };
}

export function outcomeFromError(e: unknown): ScanOutcome {
  const offline = e instanceof ApiError && (e.status === 0 || e.code === "network" || e.code === "timeout");
  return {
    tone: "error",
    title: offline ? "No connection" : "Cannot check in",
    detail: offline ? "Check the signal and scan again. Nothing was recorded." : messageFor(e),
  };
}

/**
 * Stops a camera that sees the same code 30 times a second from sending 30 requests: the same text
 * is ignored for a short window, and nothing new is accepted while a request is in flight.
 */
export class ScanGate {
  private last = "";
  private lastAt = 0;
  private busy = false;
  constructor(private readonly windowMs = 3000, private readonly now: () => number = () => Date.now()) {}

  /** True if this scan should be processed; the caller must then call done(). */
  begin(text: string): boolean {
    const value = text.trim();
    if (!value || this.busy) return false;
    if (value === this.last && this.now() - this.lastAt < this.windowMs) return false;
    this.last = value;
    this.lastAt = this.now();
    this.busy = true;
    return true;
  }

  done(): void { this.busy = false; }
}
