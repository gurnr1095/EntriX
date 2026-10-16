import { useEffect, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { CalendarDays } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/page-state";
import { QrScanner } from "@/components/qr-scanner";
import { RequireRole } from "@/components/require-role";
import { RequireSignIn } from "@/components/require-sign-in";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { tokenFromHash } from "@/lib/scan";
import { isOrganizer } from "@/hooks/use-me";
import type { EventOut, Role } from "@/types";

export const Route = createFileRoute("/scan")({
  head: () => ({ meta: [{ title: "Scan check-ins | EntriX" }, { name: "description", content: "Check participants in at the entrance." }, { property: "og:title", content: "Scan check-ins | EntriX" }, { property: "og:type", content: "website" }, { name: "twitter:card", content: "summary" }] }),
  component: Page,
});

const STORE = "entrix:scan-event";
const read = () => { try { return localStorage.getItem(STORE); } catch { return null; } };
const write = (v: string) => { try { localStorage.setItem(STORE, v); } catch { /* ignore */ } };

function Page() {
  return (
    <section className="mx-auto max-w-xl">
      <PageHeader title="Check-in" />
      <RequireSignIn what="the scanner">
        <RequireRole roles={["volunteer", "organizer", "admin"]}>{(role) => <Scanner role={role} />}</RequireRole>
      </RequireSignIn>
    </section>
  );
}

function Scanner({ role }: { role: Role }) {
  // Organizers see every event (including closed ones); volunteers see the published ones.
  const events = useQuery({
    queryKey: ["scan-events", isOrganizer(role)],
    queryFn: async (): Promise<EventOut[]> => (isOrganizer(role) ? api.orgEvents() : (await api.listEvents()).items),
  });
  // This component only renders after sign-in and the role check, so it never runs on the server.
  const [eventId, setEventId] = useState<string | null>(() => read());
  const [linkToken, setLinkToken] = useState<string | null>(() => tokenFromHash(window.location.hash));
  const clearLink = () => { setLinkToken(null); try { history.replaceState(null, "", window.location.pathname); } catch { /* ignore */ } };

  useEffect(() => {
    if (!events.data) return;
    if (eventId && !events.data.some((e) => e.id === eventId)) { setEventId(null); return; } // a stale saved choice
    if (!eventId) {
      // Nothing chosen yet: start on the first published event so the camera is ready at once.
      const first = events.data.find((e) => e.status === "published") ?? events.data[0];
      if (first) { setEventId(first.id); write(first.id); }
    }
  }, [events.data, eventId]);

  if (events.isPending) return <ListSkeleton rows={1} />;
  if (events.isError) return <ErrorState error={events.error} onRetry={() => void events.refetch()} />;
  if (events.data.length === 0) {
    return <EmptyState icon={<CalendarDays className="size-6 text-muted-foreground" />} title="No events to scan for">There are no published events yet.</EmptyState>;
  }

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Label htmlFor="scan-event">Event</Label>
        <Select value={eventId ?? ""} onValueChange={(v) => { setEventId(v); write(v); }}>
          <SelectTrigger id="scan-event" className="min-h-11"><SelectValue placeholder="Choose the event you are checking in" /></SelectTrigger>
          <SelectContent>
            {events.data.map((e) => <SelectItem key={e.id} value={e.id}>{e.name}{e.status !== "published" ? ` (${e.status})` : ""}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>
      {eventId ? <QrScanner key={eventId} eventId={eventId} initialToken={linkToken} onInitialTokenUsed={clearLink} /> : (
        <p className="rounded-none bg-muted/50 p-4 text-center text-sm text-muted-foreground">Choose an event to start scanning.</p>
      )}
    </div>
  );
}
