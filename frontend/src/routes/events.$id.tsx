import type { CSSProperties } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowLeft, CalendarDays, Clock, MapPin } from "lucide-react";
import { CategoryCard } from "@/components/category-card";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/page-state";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/errors";
import { formatDateRange, formatDateTime, registrationWindow } from "@/lib/format";
import { useEvent } from "@/lib/queries";

export const Route = createFileRoute("/events/$id")({
  head: () => ({ meta: [{ title: "Event | EntriX" }, { name: "description", content: "Event on EntriX." }, { property: "og:title", content: "Event | EntriX" }, { property: "og:description", content: "Event on EntriX." }, { property: "og:type", content: "website" }, { name: "twitter:card", content: "summary_large_image" }] }),
  component: Page,
});

function Page() {
  const { id } = Route.useParams();
  const event = useEvent(id);
  const notFound = event.error instanceof ApiError && event.error.status === 404;

  return (
    <section>
      <Link to="/" className="mb-5 inline-flex min-h-11 items-center gap-1.5 pr-3 text-base font-medium hover:text-primary-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <ArrowLeft className="size-4" />All events
      </Link>

      {event.isPending && (
        <div className="space-y-4" aria-busy="true">
          <Skeleton className="h-10 w-2/3" />
          <Skeleton className="h-5 w-1/2" />
          <ListSkeleton rows={2} />
        </div>
      )}

      {notFound && (
        <EmptyState icon={<CalendarDays className="size-6 text-muted-foreground" />} title="Event not found">
          It may have been removed or is not published yet.
        </EmptyState>
      )}
      {event.isError && !notFound && <ErrorState error={event.error} onRetry={() => void event.refetch()} />}

      {event.isSuccess && (
        <EventView event={event.data} />
      )}
    </section>
  );
}

function EventView({ event }: { event: NonNullable<ReturnType<typeof useEvent>["data"]> }) {
  const window = registrationWindow(event);
  return (
    <>
      {/* The event is the poster: its name on a flat red field, the facts under it in plain text. */}
      <div className="bleed field-dark -mt-2 mb-8 md:mb-10">
        <div className="mx-auto max-w-6xl px-4 pb-10 pt-8 md:px-8 md:pb-14 md:pt-12">
          <p className="rise mb-6 inline-block bg-primary px-3 py-1.5 text-base font-medium text-primary-foreground">
            {window === "open" ? "Registration open" : window === "upcoming" ? `Opens ${formatDateTime(event.reg_opens_at)}` : "Registration closed"}
          </p>
          <h1 className="rise break-words text-[clamp(2.25rem,7.5vw,6rem)] leading-[0.92]" style={{ "--i": 1 } as CSSProperties}>{event.name}</h1>
          <dl className="mt-8 grid gap-5 text-lg md:grid-cols-3">
            <div className="rise flex min-w-0 items-start gap-3" style={{ "--i": 2 } as CSSProperties}><CalendarDays className="mt-1 size-5 shrink-0" /><div className="min-w-0"><dt className="text-base opacity-80">When</dt><dd className="font-medium">{formatDateRange(event.starts_at, event.ends_at)}</dd></div></div>
            {event.venue && <div className="rise flex min-w-0 items-start gap-3" style={{ "--i": 3 } as CSSProperties}><MapPin className="mt-1 size-5 shrink-0" /><div className="min-w-0"><dt className="text-base opacity-80">Where</dt><dd className="break-words font-medium">{event.venue}</dd></div></div>}
            <div className="rise flex min-w-0 items-start gap-3" style={{ "--i": 4 } as CSSProperties}><Clock className="mt-1 size-5 shrink-0" /><div className="min-w-0"><dt className="text-base opacity-80">Registration</dt><dd className="font-medium">{formatDateTime(event.reg_opens_at)} to {formatDateTime(event.reg_closes_at)}</dd></div></div>
          </dl>
          {event.description && <p className="rise mt-8 max-w-3xl whitespace-pre-line text-lg leading-relaxed" style={{ "--i": 5 } as CSSProperties}>{event.description}</p>}
        </div>
      </div>

      <h2 className="mb-6 text-[clamp(1.75rem,4.5vw,3.25rem)]">Pick your sport</h2>
      {event.categories.length === 0 ? (
        <EmptyState icon={<CalendarDays className="size-6 text-muted-foreground" />} title="No categories yet">
          The organizers have not added any sports to this event.
        </EmptyState>
      ) : (
        <div className="grid gap-1.5">
          {event.categories.map((c, i) => <div key={c.id} className="rise" style={{ "--i": i } as CSSProperties}><CategoryCard category={c} window={window} /></div>)}
        </div>
      )}
    </>
  );
}
