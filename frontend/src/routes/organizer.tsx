import { useState } from "react";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarDays, MapPin, Plus } from "lucide-react";
import { toast } from "sonner";
import { EventForm } from "@/components/event-form";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/page-state";
import { RequireRole } from "@/components/require-role";
import { RequireSignIn } from "@/components/require-sign-in";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api } from "@/lib/api";
import { formatDateRange } from "@/lib/format";
import { orgKeys } from "@/lib/queries";
import { STATUS_STYLE } from "@/components/status-badge";

export const Route = createFileRoute("/organizer")({
  head: () => ({ meta: [{ title: "Organizer | EntriX" }, { name: "description", content: "Manage events on EntriX." }, { property: "og:title", content: "Organizer | EntriX" }, { property: "og:type", content: "website" }, { name: "twitter:card", content: "summary" }] }),
  component: Page,
});

function Page() {
  return (
    <section>
      <div className="mb-8 border-b border-border pb-6">
        <p className="mb-2 text-xs font-semibold uppercase text-muted-foreground">EntriX / Organizer</p>
        <h1 className="font-display text-3xl font-extrabold md:text-4xl">Your events</h1>
      </div>
      <RequireSignIn what="the organizer area">
        <RequireRole roles={["organizer", "admin"]}>{() => <Events />}</RequireRole>
      </RequireSignIn>
    </section>
  );
}

function Events() {
  const events = useQuery({ queryKey: orgKeys.events, queryFn: () => api.orgEvents() });
  const [creating, setCreating] = useState(false);
  const qc = useQueryClient();
  const navigate = useNavigate();

  return (
    <>
      <div className="mb-6 flex justify-end">
        <Button className="min-h-11 rounded-full px-6 font-semibold" onClick={() => setCreating(true)}><Plus />New event</Button>
      </div>

      {events.isPending && <ListSkeleton />}
      {events.isError && <ErrorState error={events.error} onRetry={() => void events.refetch()} />}
      {events.isSuccess && events.data.length === 0 && (
        <EmptyState icon={<CalendarDays className="size-6 text-muted-foreground" />} title="No events yet">
          Create your first event, add categories, then publish it.
        </EmptyState>
      )}
      {events.isSuccess && events.data.length > 0 && (
        <ul className="grid gap-4">
          {events.data.map((e) => (
            <li key={e.id}>
              <Link to="/organizer/events/$id" params={{ id: e.id }} className="block rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <Card className="rounded-xl shadow-card transition-shadow hover:shadow-lift">
                  <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-6">
                    <div className="min-w-0 space-y-1.5">
                      <h2 className="break-words font-display text-xl font-bold">{e.name}</h2>
                      <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
                        <span className="inline-flex items-center gap-1.5"><CalendarDays className="size-4 shrink-0 text-primary" />{formatDateRange(e.starts_at, e.ends_at)}</span>
                        {e.venue && <span className="inline-flex items-center gap-1.5"><MapPin className="size-4 shrink-0 text-primary" />{e.venue}</span>}
                      </p>
                    </div>
                    <Badge variant="outline" className={`w-fit border-0 capitalize ${STATUS_STYLE[e.status]}`}>{e.status}</Badge>
                  </CardContent>
                </Card>
              </Link>
            </li>
          ))}
        </ul>
      )}

      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>New event</DialogTitle>
            <DialogDescription>It starts as a draft. Add categories, then publish it when you are ready.</DialogDescription>
          </DialogHeader>
          <EventForm
            mode="create"
            submitLabel="Create event"
            onSubmit={async (values) => {
              const created = await api.createEvent({
                slug: values.slug, name: values.name, description: values.description, venue: values.venue,
                starts_at: values.starts_at, ends_at: values.ends_at,
                reg_opens_at: values.reg_opens_at, reg_closes_at: values.reg_closes_at,
              });
              void qc.invalidateQueries({ queryKey: orgKeys.events });
              toast.success("Event created as a draft.");
              setCreating(false);
              await navigate({ to: "/organizer/events/$id", params: { id: created.id } });
            }}
          />
        </DialogContent>
      </Dialog>
    </>
  );
}
