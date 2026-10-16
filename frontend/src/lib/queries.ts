import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export const keys = {
  events: ["events"] as const,
  event: (id: string) => ["event", id] as const,
  myRegistrations: ["my-registrations"] as const,
  myTeams: ["my-teams"] as const,
};

export function useEvents() {
  return useInfiniteQuery({
    queryKey: keys.events,
    queryFn: ({ pageParam }) => api.listEvents(pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });
}

export function useEvent(id: string) {
  // Seats are cached by the server for 3 s; keep this fresh so a full category is noticed quickly.
  return useQuery({ queryKey: keys.event(id), queryFn: () => api.getEvent(id), staleTime: 3_000 });
}

export function useMyRegistrations(enabled: boolean) {
  return useInfiniteQuery({
    queryKey: keys.myRegistrations,
    queryFn: ({ pageParam }) => api.myRegistrations(pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    enabled,
  });
}

export const orgKeys = {
  events: ["org-events"] as const,
  event: (id: string) => ["org-event", id] as const,
  stats: (id: string) => ["org-stats", id] as const,
  regs: (id: string, category: string, status: string) => ["org-regs", id, category, status] as const,
};
