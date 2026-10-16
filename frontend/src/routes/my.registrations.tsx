import { useState } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CalendarDays, MapPin, QrCode, Ticket } from "lucide-react";
import { toast } from "sonner";
import { EmptyState, ErrorState, ListSkeleton, Spinner } from "@/components/page-state";
import { QrDialog } from "@/components/qr-dialog";
import { RequireSignIn } from "@/components/require-sign-in";
import { RegStatusBadge } from "@/components/status-badge";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useMe } from "@/hooks/use-me";
import { api } from "@/lib/api";
import { messageFor } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";
import { keys, useMyRegistrations } from "@/lib/queries";
import { clearCachedQr } from "@/lib/qr-cache";
import { registrationActions } from "@/lib/registration";
import type { MyRegistration } from "@/types";

export const Route = createFileRoute("/my/registrations")({
  head: () => ({ meta: [{ title: "My registrations | EntriX" }, { name: "description", content: "My registrations on EntriX." }, { property: "og:title", content: "My registrations | EntriX" }, { property: "og:description", content: "My registrations on EntriX." }, { property: "og:type", content: "website" }, { name: "twitter:card", content: "summary_large_image" }] }),
  component: Page,
});

function Page() {
  return (
    <section>
      <div className="mb-8 border-b border-border pb-6">
        <p className="mb-2 text-xs font-semibold uppercase text-muted-foreground">EntriX / My registrations</p>
        <h1 className="font-display text-3xl font-extrabold md:text-4xl">My registrations</h1>
      </div>
      <RequireSignIn what="your registrations">
        <Registrations />
      </RequireSignIn>
    </section>
  );
}

function Registrations() {
  const { data: me } = useMe();
  const list = useMyRegistrations(true);
  const [qrFor, setQrFor] = useState<MyRegistration | null>(null);
  const [cancelFor, setCancelFor] = useState<MyRegistration | null>(null);
  const qc = useQueryClient();

  const cancel = useMutation({
    mutationFn: (r: MyRegistration) => api.cancelRegistration(r.registration_id),
    onSuccess: (_data, r) => {
      clearCachedQr(r.registration_id);
      toast.success("Registration cancelled.");
      void qc.invalidateQueries({ queryKey: keys.myRegistrations });
      void qc.invalidateQueries({ queryKey: keys.event(r.event_id) });
    },
    onError: (e) => {
      toast.error(messageFor(e));
      void qc.invalidateQueries({ queryKey: keys.myRegistrations }); // show what is true now
    },
    onSettled: () => setCancelFor(null),
  });

  const items = list.data?.pages.flatMap((p) => p.items) ?? [];

  if (list.isPending) return <ListSkeleton />;
  if (list.isError) return <ErrorState error={list.error} onRetry={() => void list.refetch()} />;
  if (items.length === 0) {
    return (
      <EmptyState icon={<Ticket className="size-6 text-muted-foreground" />} title="No registrations yet">
        <p className="mb-4">When you register for an event it shows up here, with your QR code.</p>
        <Button asChild className="min-h-11 rounded-full px-6 font-semibold"><Link to="/">Browse events</Link></Button>
      </EmptyState>
    );
  }

  return (
    <>
      <ul className="grid gap-4">
        {items.map((r) => {
          const { canShowQr, canCancel } = registrationActions(r.status);
          return (
            <li key={r.registration_id}>
              <Card className={`rounded-xl shadow-card ${r.status === "cancelled" ? "bg-muted/40" : ""}`}>
                <CardContent className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-6">
                  <div className="min-w-0 space-y-1.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <RegStatusBadge status={r.status} />
                      {r.status === "waitlisted" && r.waitlist_position != null && (
                        <span className="text-sm font-semibold">Waitlist position {r.waitlist_position}</span>
                      )}
                    </div>
                    <Link to="/events/$id" params={{ id: r.event_id }} className="block break-words font-display text-xl font-bold hover:text-primary">
                      {r.event_name}
                    </Link>
                    <p className="break-words text-sm font-medium">
                      {r.category_name} <span className="font-normal capitalize text-muted-foreground">· {r.sport.replace(/-/g, " ")}</span>
                      {r.team_name && <span className="font-normal text-muted-foreground"> · team {r.team_name}</span>}
                    </p>
                    <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
                      <span className="inline-flex items-center gap-1.5"><CalendarDays className="size-4 shrink-0 text-primary" />{formatDateTime(r.event_starts_at)}</span>
                      {r.venue && <span className="inline-flex min-w-0 items-center gap-1.5"><MapPin className="size-4 shrink-0 text-primary" />{r.venue}</span>}
                    </p>
                  </div>
                  {(canShowQr || canCancel) && (
                    <div className="flex shrink-0 flex-col gap-2 sm:items-end [&_button]:w-full sm:[&_button]:w-auto">
                      {canShowQr && (
                        <Button className="min-h-11 rounded-full px-6 font-semibold" onClick={() => setQrFor(r)}>
                          <QrCode />Show QR
                        </Button>
                      )}
                      {canCancel && (
                        <Button variant="outline" className="min-h-11 rounded-full px-6" onClick={() => setCancelFor(r)}>Cancel</Button>
                      )}
                    </div>
                  )}
                </CardContent>
              </Card>
            </li>
          );
        })}
      </ul>

      {list.hasNextPage && (
        <div className="mt-6 flex justify-center">
          <Button variant="outline" className="min-h-11 rounded-full px-6" onClick={() => void list.fetchNextPage()} disabled={list.isFetchingNextPage}>
            {list.isFetchingNextPage ? <Spinner label="Loading..." /> : "Load more"}
          </Button>
        </div>
      )}

      <QrDialog registration={qrFor} participantName={me?.name} onClose={() => setQrFor(null)} />

      <AlertDialog open={cancelFor !== null} onOpenChange={(o) => { if (!o && !cancel.isPending) setCancelFor(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Cancel this registration?</AlertDialogTitle>
            <AlertDialogDescription>
              {cancelFor?.category_name} at {cancelFor?.event_name}. Your seat is released
              {cancelFor?.status === "confirmed" ? " to the next person on the waitlist" : ""} and this cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={cancel.isPending}>Keep my spot</AlertDialogCancel>
            <AlertDialogAction
              disabled={cancel.isPending}
              onClick={(e) => { e.preventDefault(); if (cancelFor) cancel.mutate(cancelFor); }}
            >
              {cancel.isPending ? <Spinner label="Cancelling..." /> : "Cancel registration"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
