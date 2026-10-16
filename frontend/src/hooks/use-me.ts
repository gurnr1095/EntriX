import { useAuth } from "@clerk/clerk-react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Role } from "@/types";

/** The EntriX profile and role. The role comes from the database, never from Clerk. */
export function useMe() {
  const { isLoaded, isSignedIn } = useAuth();
  const query = useQuery({
    queryKey: ["me"],
    queryFn: () => api.me(),
    enabled: isLoaded && !!isSignedIn,
    staleTime: 60_000,
  });
  return { ...query, isLoaded, isSignedIn: !!isSignedIn };
}

export const isOrganizer = (role: Role | undefined) => role === "organizer" || role === "admin";
export const canScan = (role: Role | undefined) => isOrganizer(role) || role === "volunteer";
