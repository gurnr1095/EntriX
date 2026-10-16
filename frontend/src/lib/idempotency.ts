import { useRef, useState, useCallback } from "react";
import { ApiError } from "@/lib/errors";

/**
 * One in-flight action with a stable Idempotency-Key.
 * - A new key is created per user attempt.
 * - If the call fails in a way where the outcome is unknown (network, timeout, 5xx), the SAME key
 *   is reused when the user taps again, so the server can never register twice.
 * - After a definitive answer (success or a 4xx business error) the key is discarded.
 */
export function useIdempotentAction<R>(run: (key: string) => Promise<R>) {
  const key = useRef<string | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const lock = useRef(false);

  const fire = useCallback(async (): Promise<R | undefined> => {
    if (lock.current) return undefined;              // double tap guard
    lock.current = true; setPending(true); setError(null);
    key.current ??= crypto.randomUUID();
    try {
      const result = await run(key.current);
      key.current = null;
      return result;
    } catch (e) {
      const unknown = !(e instanceof ApiError) || e.status === 0 || e.status >= 500;
      if (!unknown) key.current = null;              // definitive: next tap is a new attempt
      setError(e);
      return undefined;
    } finally { lock.current = false; setPending(false); }
  }, [run]);

  return { fire, pending, error, clearError: () => setError(null) };
}
