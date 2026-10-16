import { useAuth } from "@clerk/clerk-react";
import { setTokenGetter } from "@/lib/api";

/**
 * Gives api.ts a way to fetch a FRESH Clerk session token for every request (they live 60 s,
 * so they are never stored). Assigned during render so that child queries, which run in
 * effects after this component, always see it.
 */
export function AuthBridge() {
  const { getToken } = useAuth();
  setTokenGetter((opts) => getToken(opts?.skipCache ? { skipCache: true } : undefined));
  return null;
}
