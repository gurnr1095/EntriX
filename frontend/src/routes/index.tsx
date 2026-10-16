import type { CSSProperties } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowDown, CalendarDays, MapPin } from "lucide-react";
import track from "@/assets/track.jpg";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, ListSkeleton, Spinner } from "@/components/page-state";
import { WindowBadge } from "@/components/status-badge";
import { formatDateRange, formatDateTime, registrationWindow } from "@/lib/format";
import { useEvents } from "@/lib/queries";

export const Route = createFileRoute("/")({
  head: () => ({ meta: [{ title: "Events | EntriX" }, { name: "description", content: "Register for college sports events: pick a sport, grab a seat, show your QR pass at the gate." }, { property: "og:title", content: "Events | EntriX" }, { property: "og:description", content: "Register for college sports events in minutes." }, { property: "og:type", content: "website" }, { name: "twitter:card", content: "summary_large_image" }] }),
  component: Index,
});

const delay = (i: number) => ({ "--i": i }) as CSSProperties;

function Index() {
  const events = useEvents();
  const items = events.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <>
      {/* Hero: the photograph is the background, with a flat dark overlay so the white headline always reads. */}
      <div className="bleed relative isolate -mt-6 overflow-hidden bg-black md:-mt-10">
        <div className="shutter absolute inset-0 -z-20">
          <img src={track} alt="" width={1536} height={512} className="h-full w-full object-cover" />
        </div>
        <div className="absolute inset-0 -z-10 bg-black/55" aria-hidden />
        <div className="mx-auto flex min-h-[26rem] max-w-6xl flex-col justify-end gap-6 px-4 pb-10 pt-24 text-white md:min-h-[34rem] md:gap-8 md:px-8 md:pb-16 md:pt-36">
          <h1 className="rise text-[clamp(2rem,10.4vw,5.5rem)] leading-[0.88] md:text-[clamp(4rem,9vw,8.5rem)]">Get in<br />the game</h1>
          <div className="flex flex-col items-start gap-5 md:flex-row md:items-center md:justify-between">
            <p className="rise max-w-[40ch] text-lg md:text-xl" style={delay(2)}>
              Pick a sport, grab a seat, and show your QR pass at the gate.
            </p>
            <Button asChild className="rise min-h-12 px-8 text-base font-semibold" style={delay(3)}>
              <a href="#events">See events <ArrowDown /></a>
            </Button>
          </div>
        </div>
      </div>

      <section id="events" className="scroll-mt-6 pt-16 md:pt-24">
        <div className="mb-8 flex items-end justify-between gap-4">
          <h2 className="rise text-[clamp(1.75rem,4.5vw,3.25rem)]">Upcoming events</h2>
          {events.isSuccess && <span className="shrink-0 pb-1 text-lg font-medium">{items.length} {items.length === 1 ? "event" : "events"}</span>}
        </div>

        {events.isPending && <ListSkeleton />}
        {events.isError && <ErrorState error={events.error} onRetry={() => void events.refetch()} />}
        {events.isSuccess && items.length === 0 && (
          <EmptyState icon={<CalendarDays className="size-6 text-muted-foreground" strokeWidth={1.5} />} title="No events yet">
            The next starting line is on its way.
          </EmptyState>
        )}
        {items.length > 0 && (
          <ul className="grid gap-1.5">
            {items.map((e, i) => (
              <li key={e.id} className="rise" style={delay(i)}>
                <Link to="/events/$id" params={{ id: e.id }}
                  className="group grid gap-2 bg-card p-4 hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:grid-cols-[1fr_auto] md:items-center md:p-5">
                  <div className="min-w-0 space-y-1">
                    <h3 className="break-words text-xl font-medium group-hover:text-primary-text md:text-2xl">{e.name}</h3>
                    <p className="flex flex-wrap items-center gap-x-5 gap-y-1 text-base text-muted-foreground">
                      <span className="inline-flex items-center gap-1.5"><CalendarDays className="size-4 shrink-0" />{formatDateRange(e.starts_at, e.ends_at)}</span>
                      {e.venue && <span className="inline-flex min-w-0 items-center gap-1.5"><MapPin className="size-4 shrink-0" />{e.venue}</span>}
                    </p>
                  </div>
                  <div className="justify-self-start md:justify-self-end">
                    <WindowBadge window={registrationWindow(e)} opensLabel={`Opens ${formatDateTime(e.reg_opens_at)}`} />
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
        {events.hasNextPage && (
          <div className="mt-8 flex justify-center">
            <Button variant="outline" className="min-h-12 px-8" onClick={() => void events.fetchNextPage()} disabled={events.isFetchingNextPage}>
              {events.isFetchingNextPage ? <Spinner label="Loading..." /> : "Load more"}
            </Button>
          </div>
        )}
      </section>
    </>
  );
}
