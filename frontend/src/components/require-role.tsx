import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/page-state";
import { useMe } from "@/hooks/use-me";
import type { Role } from "@/types";

/**
 * Hides staff screens from people who cannot use them. This is only courtesy: the server refuses
 * every staff request from anyone else with a 403, whatever this component shows.
 */
export function RequireRole({ roles, children }: { roles: readonly Role[]; children: (role: Role) => ReactNode }) {
  const me = useMe();
  if (me.isPending) return <ListSkeleton rows={2} />;
  if (me.isError) return <ErrorState error={me.error} onRetry={() => void me.refetch()} />;
  if (!roles.includes(me.data.role)) {
    return (
      <EmptyState icon={<ShieldAlert className="size-6 text-muted-foreground" />} title="This page is for event staff">
        <p className="mb-4">Your account does not have access. Ask an organizer if you should.</p>
        <Button asChild className="min-h-11 rounded-full px-6 font-semibold"><Link to="/">Back to events</Link></Button>
      </EmptyState>
    );
  }
  return <>{children(me.data.role)}</>;
}
