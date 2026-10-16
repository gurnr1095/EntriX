import { useState } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Download, ExternalLink, Pencil, Plus, Users } from "lucide-react";
import { toast } from "sonner";
import { CategoryDialog } from "@/components/category-dialog";
import { EventForm } from "@/components/event-form";
import { EmptyState, ErrorState, ListSkeleton, Spinner } from "@/components/page-state";
import { RequireRole } from "@/components/require-role";
import { RequireSignIn } from "@/components/require-sign-in";
import { RegStatusBadge, STATUS_STYLE } from "@/components/status-badge";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { ApiError, messageFor } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";
import { nextStatus, nextStatusLabel, nextStatusWarning } from "@/lib/organizer";
import { orgKeys } from "@/lib/queries";
import type { Category, EventDetail, RegStatus } from "@/types";

export const Route = createFileRoute("/organizer_/events/$id")({
  head: () => ({ meta: [{ title: "Manage event | EntriX" }, { name: "description", content: "Manage an event on EntriX." }, { property: "og:title", content: "Manage event | EntriX" }, { property: "og:type", content: "website" }, { name: "twitter:card", content: "summary" }] }),
  component: Page,
});

function Page() {
  const { id } = Route.useParams();
  return (
    <section>
      <Link to="/organizer" className="mb-5 inline-flex min-h-11 items-center gap-1.5 text-sm font-medium text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" />All events
      </Link>
      <RequireSignIn what="the organizer area">
        <RequireRole roles={["organizer", "admin"]}>{() => <Manager id={id} />}</RequireRole>
      </RequireSignIn>
    </section>
  );
}

function Manager({ id }: { id: string }) {
  const event = useQuery({ queryKey: orgKeys.event(id), queryFn: () => api.orgEvent(id) });
  const qc = useQueryClient();
  const [confirmStep, setConfirmStep] = useState(false);

  const step = useMutation({
    mutationFn: (status: "published" | "closed") => api.patchEvent(id, { status }),
    onSuccess: (e) => {
      toast.success(e.status === "published" ? "Event published." : "Event closed.");
      void qc.invalidateQueries({ queryKey: orgKeys.event(id) });
      void qc.invalidateQueries({ queryKey: orgKeys.events });
      void qc.invalidateQueries({ queryKey: ["events"] });
    },
    onError: (e) => toast.error(messageFor(e)),
    onSettled: () => setConfirmStep(false),
  });

  if (event.isPending) return <ListSkeleton rows={2} />;
  if (event.isError) {
    return event.error instanceof ApiError && event.error.status === 404
      ? <EmptyState icon={<Users className="size-6 text-muted-foreground" />} title="Event not found">It may have been removed.</EmptyState>
      : <ErrorState error={event.error} onRetry={() => void event.refetch()} />;
  }
  const e = event.data;
  const next = nextStatus(e.status);

  return (
    <>
      <div className="mb-6 flex flex-col gap-4 border-b border-border pb-6 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 space-y-2">
          <Badge variant="outline" className={`border-0 capitalize ${STATUS_STYLE[e.status]}`}>{e.status}</Badge>
          <h1 className="break-words font-display text-3xl font-extrabold md:text-4xl">{e.name}</h1>
          {e.status !== "draft" && (
            <Link to="/events/$id" params={{ id }} className="inline-flex items-center gap-1.5 text-sm text-primary hover:underline">
              <ExternalLink className="size-4" />View public page
            </Link>
          )}
        </div>
        {next && (
          <Button className="min-h-11 shrink-0 rounded-full px-6 font-semibold" variant={e.status === "draft" ? "default" : "outline"} onClick={() => setConfirmStep(true)}>
            {nextStatusLabel(e.status)}
          </Button>
        )}
      </div>

      <Tabs defaultValue="overview">
        <TabsList className="mb-6 h-auto flex-wrap">
          <TabsTrigger value="overview" className="min-h-11">Overview</TabsTrigger>
          <TabsTrigger value="categories" className="min-h-11">Categories</TabsTrigger>
          <TabsTrigger value="stats" className="min-h-11">Stats</TabsTrigger>
          <TabsTrigger value="registrations" className="min-h-11">Registrations</TabsTrigger>
        </TabsList>
        <TabsContent value="overview"><Overview event={e} /></TabsContent>
        <TabsContent value="categories"><Categories event={e} /></TabsContent>
        <TabsContent value="stats"><Stats event={e} /></TabsContent>
        <TabsContent value="registrations"><Registrations event={e} /></TabsContent>
      </Tabs>

      <AlertDialog open={confirmStep} onOpenChange={(o) => { if (!o && !step.isPending) setConfirmStep(false); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{nextStatusLabel(e.status)}?</AlertDialogTitle>
            <AlertDialogDescription>{nextStatusWarning(e.status)}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={step.isPending}>Not yet</AlertDialogCancel>
            <AlertDialogAction disabled={step.isPending} onClick={(ev) => { ev.preventDefault(); if (next === "published" || next === "closed") step.mutate(next); }}>
              {step.isPending ? <Spinner label="Working..." /> : nextStatusLabel(e.status)}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

function Overview({ event }: { event: EventDetail }) {
  const qc = useQueryClient();
  return (
    <Card className="max-w-2xl rounded-xl shadow-card">
      <CardContent className="p-5 sm:p-6">
        <EventForm
          mode="edit"
          initial={event}
          submitLabel="Save changes"
          onSubmit={async (v) => {
            await api.patchEvent(event.id, {
              name: v.name, description: v.description, venue: v.venue, starts_at: v.starts_at,
              ends_at: v.ends_at, reg_opens_at: v.reg_opens_at, reg_closes_at: v.reg_closes_at,
            });
            toast.success("Event saved.");
            void qc.invalidateQueries({ queryKey: orgKeys.event(event.id) });
            void qc.invalidateQueries({ queryKey: orgKeys.events });
            void qc.invalidateQueries({ queryKey: ["event", event.id] });
          }}
        />
      </CardContent>
    </Card>
  );
}

function Categories({ event }: { event: EventDetail }) {
  const qc = useQueryClient();
  const [dialog, setDialog] = useState<{ category?: Category } | null>(null);
  const toggle = useMutation({
    mutationFn: ({ c, on }: { c: Category; on: boolean }) => api.patchCategory(c.id, { waitlist_enabled: on }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: orgKeys.event(event.id) });
      void qc.invalidateQueries({ queryKey: ["event", event.id] });
    },
    onError: (e) => toast.error(messageFor(e)),
  });

  return (
    <>
      <div className="mb-5 flex justify-end">
        <Button className="min-h-11 rounded-full px-6 font-semibold" onClick={() => setDialog({})}><Plus />Add category</Button>
      </div>
      {event.categories.length === 0 ? (
        <EmptyState icon={<Users className="size-6 text-muted-foreground" />} title="No categories yet">
          Add the sports people can register for. An event needs at least one before it is useful.
        </EmptyState>
      ) : (
        <ul className="grid gap-4">
          {event.categories.map((c) => {
            const pct = Math.min(100, Math.round((c.confirmed_count / c.capacity) * 100));
            return (
              <li key={c.id}>
                <Card className="rounded-xl shadow-card">
                  <CardContent className="space-y-4 p-4 sm:p-6">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <h3 className="break-words font-display text-lg font-bold">{c.name}</h3>
                        <p className="text-sm text-muted-foreground">
                          <span className="capitalize">{c.sport.replace(/-/g, " ")}</span> ·{" "}
                          {c.participation === "team" ? `teams of ${c.team_size_min} to ${c.team_size_max}` : "individual"}
                        </p>
                      </div>
                      <Button variant="outline" className="min-h-11 rounded-full px-5" onClick={() => setDialog({ category: c })}><Pencil />Edit</Button>
                    </div>
                    <div className="space-y-1.5">
                      <Progress value={pct} aria-label={`${pct}% full`} />
                      <p className="text-sm text-muted-foreground">{c.confirmed_count} of {c.capacity} {c.participation === "team" ? "teams" : "seats"} taken</p>
                    </div>
                    <div className="flex items-center justify-between gap-4 rounded-xl bg-muted/50 px-4 py-3">
                      <Label htmlFor={`wl-${c.id}`} className="text-sm">Waitlist when full</Label>
                      <Switch id={`wl-${c.id}`} checked={c.waitlist_enabled} disabled={toggle.isPending}
                        onCheckedChange={(on) => toggle.mutate({ c, on })} />
                    </div>
                  </CardContent>
                </Card>
              </li>
            );
          })}
        </ul>
      )}
      <CategoryDialog
        open={dialog !== null}
        onOpenChange={(o) => { if (!o) setDialog(null); }}
        eventId={event.id}
        category={dialog?.category}
        onSaved={() => setDialog(null)}
      />
    </>
  );
}

function Stats({ event }: { event: EventDetail }) {
  const stats = useQuery({
    queryKey: orgKeys.stats(event.id),
    queryFn: () => api.stats(event.id),
    refetchInterval: 15_000, // stops while the tab is hidden
  });
  if (stats.isPending) return <ListSkeleton rows={2} />;
  if (stats.isError) return <ErrorState error={stats.error} onRetry={() => void stats.refetch()} />;
  const rows = stats.data.categories;
  const total = rows.reduce((a, r) => ({ confirmed: a.confirmed + r.confirmed, waitlisted: a.waitlisted + r.waitlisted, checked: a.checked + r.checked_in }), { confirmed: 0, waitlisted: 0, checked: 0 });
  if (rows.length === 0) return <EmptyState icon={<Users className="size-6 text-muted-foreground" />} title="Nothing to count yet">Add categories first.</EmptyState>;

  return (
    <div className="space-y-6">
      <dl className="grid grid-cols-3 gap-3 text-center">
        {([["Confirmed", total.confirmed], ["Waitlisted", total.waitlisted], ["Checked in", total.checked]] as const).map(([label, n]) => (
          <div key={label} className="rounded-xl bg-muted/50 p-4">
            <dd className="font-display text-3xl font-extrabold">{n}</dd>
            <dt className="text-xs text-muted-foreground">{label}</dt>
          </div>
        ))}
      </dl>
      <ul className="grid gap-4">
        {rows.map((r) => (
          <li key={r.id}>
            <Card className="rounded-xl shadow-card">
              <CardContent className="space-y-3 p-4 sm:p-6">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h3 className="font-display text-lg font-bold">{r.name}</h3>
                  <p className="text-sm text-muted-foreground">{r.confirmed} of {r.capacity} taken</p>
                </div>
                <Progress value={Math.min(100, Math.round((r.confirmed / r.capacity) * 100))} aria-label={`${r.name} fill level`} />
                <p className="text-sm text-muted-foreground">{r.waitlisted} on the waitlist · {r.checked_in} checked in</p>
              </CardContent>
            </Card>
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted-foreground">Refreshes every 15 seconds.</p>
    </div>
  );
}

const STATUSES: RegStatus[] = ["confirmed", "waitlisted", "checked_in", "cancelled"];

function Registrations({ event }: { event: EventDetail }) {
  const [category, setCategory] = useState("all");
  const [status, setStatus] = useState("all");
  const [downloading, setDownloading] = useState(false);
  const list = useInfiniteQuery({
    queryKey: orgKeys.regs(event.id, category, status),
    queryFn: ({ pageParam }) => api.registrations(event.id, {
      ...(category !== "all" ? { category_id: category } : {}),
      ...(status !== "all" ? { status } : {}),
      cursor: pageParam,
    }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const rows = list.data?.pages.flatMap((p) => p.items) ?? [];

  async function csv() {
    setDownloading(true);
    try { await api.downloadCsv(event.id, event.slug); } catch (e) { toast.error(messageFor(e)); } finally { setDownloading(false); }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <div className="flex-1 space-y-2">
          <Label htmlFor="f-cat">Category</Label>
          <Select value={category} onValueChange={setCategory}>
            <SelectTrigger id="f-cat" className="min-h-11"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All categories</SelectItem>
              {event.categories.map((c) => <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="flex-1 space-y-2">
          <Label htmlFor="f-status">Status</Label>
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger id="f-status" className="min-h-11"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Any status</SelectItem>
              {STATUSES.map((s) => <SelectItem key={s} value={s} className="capitalize">{s.replace("_", " ")}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <Button variant="outline" className="min-h-11 rounded-full px-5" onClick={() => void csv()} disabled={downloading}>
          {downloading ? <Spinner label="Preparing..." /> : <><Download />Download CSV</>}
        </Button>
      </div>

      {list.isPending && <ListSkeleton rows={3} />}
      {list.isError && <ErrorState error={list.error} onRetry={() => void list.refetch()} />}
      {list.isSuccess && rows.length === 0 && (
        <EmptyState icon={<Users className="size-6 text-muted-foreground" />} title="No registrations match">Try a different filter.</EmptyState>
      )}

      {rows.length > 0 && (
        <>
          <div className="hidden md:block">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead><TableHead>Category</TableHead><TableHead>College</TableHead>
                  <TableHead>Contact</TableHead><TableHead>Status</TableHead><TableHead>Registered</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((r) => (
                  <TableRow key={r.registration_id}>
                    <TableCell className="font-medium">{r.participant.name}{r.team_name && <span className="block text-xs font-normal text-muted-foreground">team {r.team_name}</span>}</TableCell>
                    <TableCell>{r.category_name}</TableCell>
                    <TableCell>{[r.participant.college, r.participant.roll_no].filter(Boolean).join(" · ") || "-"}</TableCell>
                    <TableCell className="text-sm">{r.participant.email}{r.participant.phone && <span className="block text-muted-foreground">{r.participant.phone}</span>}</TableCell>
                    <TableCell><RegStatusBadge status={r.status} /></TableCell>
                    <TableCell className="text-sm text-muted-foreground">{formatDateTime(r.created_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <ul className="grid gap-3 md:hidden">
            {rows.map((r) => (
              <li key={r.registration_id}>
                <Card className="rounded-xl shadow-card">
                  <CardContent className="space-y-1.5 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <p className="break-words font-semibold">{r.participant.name}</p>
                      <RegStatusBadge status={r.status} />
                    </div>
                    <p className="text-sm">{r.category_name}{r.team_name ? ` · team ${r.team_name}` : ""}</p>
                    <p className="break-all text-sm text-muted-foreground">{r.participant.email}{r.participant.phone ? ` · ${r.participant.phone}` : ""}</p>
                    {(r.participant.college || r.participant.roll_no) && <p className="text-sm text-muted-foreground">{[r.participant.college, r.participant.roll_no].filter(Boolean).join(" · ")}</p>}
                  </CardContent>
                </Card>
              </li>
            ))}
          </ul>
        </>
      )}

      {list.hasNextPage && (
        <div className="flex justify-center">
          <Button variant="outline" className="min-h-11 rounded-full px-6" onClick={() => void list.fetchNextPage()} disabled={list.isFetchingNextPage}>
            {list.isFetchingNextPage ? <Spinner label="Loading..." /> : "Load more"}
          </Button>
        </div>
      )}
    </div>
  );
}
