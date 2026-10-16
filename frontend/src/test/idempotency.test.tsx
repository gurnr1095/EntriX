import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { useIdempotentAction } from "@/lib/idempotency";
import { ApiError } from "@/lib/errors";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/** Minimal renderHook (the testing-library one needs an extra peer package). */
function renderHook<R>(hook: () => R) {
  const result = { current: undefined as unknown as R };
  function Probe() { result.current = hook(); return null; }
  const root = createRoot(document.createElement("div"));
  act(() => { root.render(<Probe />); });
  return { result };
}

describe("useIdempotentAction", () => {
  it("reuses the key after an unknown outcome and discards it after a definitive answer", async () => {
    const keys: string[] = [];
    const outcomes: Array<Error | string> = [new ApiError(0, "network", "x"), new ApiError(503, "http_error", "x"), "ok", new ApiError(409, "category_full", "x"), "ok2"];
    const run = vi.fn(async (key: string) => {
      keys.push(key);
      const o = outcomes.shift()!;
      if (o instanceof Error) throw o;
      return o;
    });
    const { result } = renderHook(() => useIdempotentAction(run));
    await act(async () => { await result.current.fire(); });  // network error
    await act(async () => { await result.current.fire(); });  // 503
    await act(async () => { expect(await result.current.fire()).toBe("ok"); });
    expect(keys[0]).toBe(keys[1]);
    expect(keys[1]).toBe(keys[2]);                              // all one attempt
    await act(async () => { await result.current.fire(); });  // new attempt: business error
    await act(async () => { await result.current.fire(); });  // definitive, so a NEW key
    expect(keys[3]).not.toBe(keys[2]);
    expect(keys[4]).not.toBe(keys[3]);
  });

  it("ignores a second tap while the first is in flight", async () => {
    let release!: (v: string) => void;
    const run = vi.fn(() => new Promise<string>((r) => { release = r; }));
    const { result } = renderHook(() => useIdempotentAction(run));
    let first!: Promise<string | undefined>;
    await act(async () => { first = result.current.fire(); void result.current.fire(); void result.current.fire(); });
    expect(run).toHaveBeenCalledTimes(1);
    await act(async () => { release("done"); await first; });
  });
});
