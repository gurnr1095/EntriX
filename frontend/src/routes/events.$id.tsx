import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowLeft, CalendarDays, Clock, MapPin } from "lucide-react";
import { CategoryCard } from "@/components/category-card";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/page-state";
import { WindowBadge } from "@/components/status-badge";
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
      <Link to="/" className="mb-5 inline-flex min-h-11 items-center gap-1.5 rounded-full pr-3 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
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
      <div className="relative mb-8 overflow-hidden rounded-2xl border border-border bg-card p-5 shadow-card sm:p-8">
        <div aria-hidden className="pointer-events-none absolute -right-16 -top-16 size-48 rounded-full bg-primary-soft blur-2xl" />
        <div className="relative">
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <WindowBadge window={window} opensLabel={`Opens ${formatDateTime(event.reg_opens_at)}`} />
          </div>
          <h1 className="break-words font-display text-3xl font-extrabold md:text-5xl">{event.name}</h1>
          <dl className="mt-5 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
            <div className="flex min-w-0 items-start gap-2.5"><CalendarDays className="mt-0.5 size-4 shrink-0 text-primary" /><div className="min-w-0"><dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">When</dt><dd className="font-medium">{formatDateRange(event.starts_at, event.ends_at)}</dd></div></div>
            {event.venue && <div className="flex min-w-0 items-start gap-2.5"><MapPin className="mt-0.5 size-4 shrink-0 text-primary" /><div className="min-w-0"><dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Where</dt><dd className="break-words font-medium">{event.venue}</dd></div></div>}
            <div className="flex min-w-0 items-start gap-2.5"><Clock className="mt-0.5 size-4 shrink-0 text-primary" /><div className="min-w-0"><dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Registration</dt><dd className="font-medium">{formatDateTime(event.reg_opens_at)} to {formatDateTime(event.reg_closes_at)}</dd></div></div>
          </dl>
          {event.description && <p className="mt-6 max-w-3xl whitespace-pre-line border-t border-border pt-5 text-sm leading-relaxed text-muted-foreground sm:text-base">{event.description}</p>}
        </div>
      </div>

      <h2 className="mb-4 font-display text-xl font-bold">Categories</h2>
      {event.categories.length === 0 ? (
        <EmptyState icon={<CalendarDays className="size-6 text-muted-foreground" />} title="No categories yet">
          The organizers have not added any sports to this event.
        </EmptyState>
      ) : (
        <div className="space-y-4">
          {event.categories.map((c) => <CategoryCard key={c.id} category={c} window={window} />)}
        </div>
      )}
    </>
  );
}
