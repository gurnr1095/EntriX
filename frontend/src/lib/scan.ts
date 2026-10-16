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

/** html5-qrcode throws strings and DOMExceptions alike; turn either into a sentence a volunteer can act on. */
export function describeCameraError(e: unknown): string {
  const text = `${(e as { name?: string } | null)?.name ?? ""} ${(e as { message?: string } | null)?.message ?? ""} ${String(e)}`.toLowerCase();
  if (typeof window !== "undefined" && window.isSecureContext === false) {
    return "The camera only works on a secure (https) page.";
  }
  if (/notallowed|permission|denied/.test(text)) {
    return "Camera access is blocked. Tap the lock icon next to the address, allow the camera for this site, then try again.";
  }
  if (/notfound|no camera|devicesnotfound|requested device not found/.test(text)) return "No camera was found on this device.";
  if (/notreadable|trackstart|in use|could not start video/.test(text)) return "Another app or tab is using the camera. Close it and try again.";
  if (/overconstrained|constraint/.test(text)) return "This camera does not support the requested mode. Try Switch camera.";
  if (/secure|https/.test(text)) return "The camera only works on a secure (https) page.";
  return "The camera could not start.";
}

/**
 * The QR shows a link, so a phone's ordinary camera app opens the scanner page instead of offering
 * the text to Notes. The token rides in the #fragment, which browsers never send to a server.
 */
export function scanLink(origin: string, token: string): string {
  return `${origin}/scan#t=${encodeURIComponent(token)}`;
}

/** The token from a scanned value: a scan link, or (older QR codes and emails) the bare token. */
export function extractToken(text: string): string {
  const value = text.trim();
  if (/^https?:\/\//i.test(value)) {
    try {
      const url = new URL(value);
      const fromHash = new URLSearchParams(url.hash.replace(/^#/, "")).get("t");
      const found = fromHash ?? url.searchParams.get("t");
      if (found) return found.trim();
    } catch { /* not a valid URL: fall through and treat it as text */ }
  }
  return value;
}

export function tokenFromHash(hash: string): string | null {
  const t = new URLSearchParams(hash.replace(/^#/, "")).get("t");
  return t ? t.trim() : null;
}
