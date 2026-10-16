import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowUpRight, CalendarDays, MapPin } from "lucide-react";
import track from "@/assets/track.jpg";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState, ErrorState, ListSkeleton, Spinner } from "@/components/page-state";
import { WindowBadge } from "@/components/status-badge";
import { formatDateRange, formatDateTime, registrationWindow } from "@/lib/format";
import { useEvents } from "@/lib/queries";

export const Route = createFileRoute("/")({
  head: () => ({ meta: [{ title: "Events | EntriX" }, { name: "description", content: "Sports events on EntriX." }, { property: "og:title", content: "Events | EntriX" }, { property: "og:description", content: "Sports events on EntriX." }, { property: "og:type", content: "website" }, { name: "twitter:card", content: "summary_large_image" }] }),
  component: Index,
});

function Index() {
  const events = useEvents();
  const items = events.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <>
      <div className="relative isolate overflow-hidden rounded-2xl bg-foreground shadow-lift">
        <img src={track} alt="A sunlit athletics track surrounding a green playing field" width={1536} height={512} className="absolute inset-0 -z-10 h-full w-full object-cover opacity-60" />
        <div className="absolute inset-0 -z-10 bg-gradient-to-t from-foreground via-foreground/60 to-transparent" />
        <div className="flex min-h-64 flex-col justify-end gap-3 p-5 text-background sm:p-8 md:min-h-80 md:p-10">
          <span className="inline-flex w-fit items-center gap-2 rounded-full bg-primary px-3 py-1 text-[11px] font-bold uppercase tracking-wider text-primary-foreground">
            <span className="size-1.5 rounded-full bg-primary-foreground" />The starting line
          </span>
          <h1 className="font-display text-4xl font-extrabold italic leading-none sm:text-5xl md:text-6xl">Events<ArrowUpRight className="ml-1 inline size-8 align-top text-primary sm:size-10" strokeWidth={3} /></h1>
          <p className="max-w-md text-sm text-background/80 sm:text-base">Your next game starts here. Every sport. One starting line.</p>
        </div>
      </div>

      <section className="mt-10">
        <div className="flex items-center justify-between gap-3 border-b border-border pb-4">
          <h2 className="font-display text-lg font-semibold">Upcoming events</h2>
          {events.isSuccess && <span className="shrink-0 rounded-full bg-muted px-2.5 py-1 text-xs font-semibold text-muted-foreground">{items.length} {items.length === 1 ? "event" : "events"}</span>}
        </div>

        <div className="pt-6">
          {events.isPending && <ListSkeleton />}
          {events.isError && <ErrorState error={events.error} onRetry={() => void events.refetch()} />}
          {events.isSuccess && items.length === 0 && (
            <EmptyState icon={<CalendarDays className="size-6 text-muted-foreground" strokeWidth={1.5} />} title="No events yet">
              The next starting line is on its way.
            </EmptyState>
          )}
          {items.length > 0 && (
            <ul className="grid gap-4">
              {items.map((e) => (
                <li key={e.id}>
                  <Link to="/events/$id" params={{ id: e.id }} className="group block rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background">
                    <Card className="relative overflow-hidden rounded-xl shadow-card transition-all duration-200 before:absolute before:inset-y-0 before:left-0 before:w-1 before:bg-primary before:opacity-0 before:transition-opacity group-hover:-translate-y-0.5 group-hover:shadow-lift group-hover:before:opacity-100 motion-reduce:group-hover:translate-y-0">
                      <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-6">
                        <div className="min-w-0 space-y-1.5">
                          <h3 className="break-words font-display text-xl font-bold transition-colors group-hover:text-primary">{e.name}</h3>
                          <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
                            <span className="inline-flex items-center gap-1.5"><CalendarDays className="size-4 shrink-0 text-primary" />{formatDateRange(e.starts_at, e.ends_at)}</span>
                            {e.venue && <span className="inline-flex min-w-0 items-center gap-1.5"><MapPin className="size-4 shrink-0 text-primary" />{e.venue}</span>}
                          </p>
                        </div>
                        <div className="self-start sm:self-auto"><WindowBadge window={registrationWindow(e)} opensLabel={`Opens ${formatDateTime(e.reg_opens_at)}`} /></div>
                      </CardContent>
                    </Card>
                  </Link>
                </li>
              ))}
            </ul>
          )}
          {events.hasNextPage && (
            <div className="mt-6 flex justify-center">
              <Button variant="outline" className="min-h-11 rounded-full px-6" onClick={() => void events.fetchNextPage()} disabled={events.isFetchingNextPage}>
                {events.isFetchingNextPage ? <Spinner label="Loading..." /> : "Load more"}
              </Button>
            </div>
          )}
        </div>
      </section>
    </>
  );
}
