/**
 * The QR token is a signed, permanent string for one registration, so it is safe to keep on the
 * device. Caching it means the code still opens at a venue with no signal. Every access is wrapped:
 * storage can be missing or blocked (private windows, server rendering).
 */
const key = (registrationId: string) => `qr:${registrationId}`;

export function getCachedQr(registrationId: string): string | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage.getItem(key(registrationId));
  } catch {
    return null;
  }
}

export function setCachedQr(registrationId: string, token: string): void {
  try {
    if (typeof localStorage !== "undefined") localStorage.setItem(key(registrationId), token);
  } catch {
    /* storage full or blocked: the QR just will not be available offline */
  }
}

export function clearCachedQr(registrationId: string): void {
  try {
    if (typeof localStorage !== "undefined") localStorage.removeItem(key(registrationId));
  } catch {
    /* ignore */
  }
}
