import { useEffect, useState } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown, Copy, Share2, Users } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/page-header";
import { EmptyState, ErrorState, ListSkeleton, Spinner } from "@/components/page-state";
import { RegistrationResultDialog } from "@/components/registration-result-dialog";
import { RequireSignIn } from "@/components/require-sign-in";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { api } from "@/lib/api";
import { ApiError, messageFor } from "@/lib/errors";
import { useIdempotentAction } from "@/lib/idempotency";
import { keys } from "@/lib/queries";
import { teamActions, teamStatusLabel } from "@/lib/teams";
import type { MyTeam, RegistrationResult } from "@/types";

export const Route = createFileRoute("/my/teams")({
  head: () => ({ meta: [{ title: "My teams | EntriX" }, { name: "description", content: "My teams on EntriX." }, { property: "og:title", content: "My teams | EntriX" }, { property: "og:type", content: "website" }, { name: "twitter:card", content: "summary" }] }),
  component: Page,
});

function Page() {
  return (
    <section>
      <PageHeader title="My teams" />
      <RequireSignIn what="your teams"><Teams /></RequireSignIn>
    </section>
  );
}

function Teams() {
  const teams = useQuery({ queryKey: keys.myTeams, queryFn: () => api.myTeams() });
  if (teams.isPending) return <ListSkeleton />;
  if (teams.isError) return <ErrorState error={teams.error} onRetry={() => void teams.refetch()} />;
  if (teams.data.length === 0) {
    return (
      <EmptyState icon={<Users className="size-6 text-muted-foreground" />} title="You are not in any team">
        <p className="mb-4">Create a team or join one with a code from an event's team category.</p>
        <Button asChild className="min-h-11 rounded-none px-6 font-semibold"><Link to="/">Browse events</Link></Button>
      </EmptyState>
    );
  }
  return <ul className="grid gap-4">{teams.data.map((t) => <li key={t.id}><TeamCard team={t} /></li>)}</ul>;
}

function InviteCode({ code, teamName }: { code: string; teamName: string }) {
  const [copied, setCopied] = useState(false);
  const canShare = typeof navigator !== "undefined" && typeof navigator.share === "function";

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Could not copy. Select the code and copy it by hand.");
    }
  }
  async function share() {
    try { await navigator.share({ title: `Join ${teamName} on EntriX`, text: `Join my team ${teamName} on EntriX with this code: ${code}` }); }
    catch { /* the person closed the share sheet */ }
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-none bg-muted/50 p-4">
      <div>
        <p className="text-xs text-muted-foreground">Invite code</p>
        <p className="select-all tabular-nums text-2xl font-bold tracking-widest" aria-label={`Invite code ${code.split("").join(" ")}`}>{code}</p>
      </div>
      <div className="flex gap-2">
        <Button variant="outline" className="min-h-11 rounded-none px-4" onClick={() => void copy()}>{copied ? <Check /> : <Copy />}{copied ? "Copied" : "Copy"}</Button>
        {canShare && <Button variant="outline" className="min-h-11 rounded-none px-4" onClick={() => void share()}><Share2 />Share</Button>}
      </div>
    </div>
  );
}

function TeamCard({ team }: { team: MyTeam }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState<"leave" | "cancel" | null>(null);
  const [result, setResult] = useState<RegistrationResult | null>(null);
  const actions = teamActions(team);

  const members = useQuery({ queryKey: ["team", team.id], queryFn: () => api.getTeam(team.id), enabled: open });

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: keys.myTeams });
    void qc.invalidateQueries({ queryKey: ["team", team.id] });
    void qc.invalidateQueries({ queryKey: keys.myRegistrations });
    void qc.invalidateQueries({ queryKey: keys.event(team.event_id) });
  };

  const register = useIdempotentAction((key) => api.registerTeam(team.id, key));
  const { error, clearError } = register;
  useEffect(() => {
    if (error == null) return;
    const unknown = !(error instanceof ApiError) || error.status === 0 || error.status >= 500;
    toast.error(unknown ? "We could not confirm the registration. Tap Register team again: it will not register twice." : messageFor(error));
    if (!unknown) refresh();
    clearError();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [error]);

  async function onRegister() {
    const r = await register.fire();
    if (r) { setResult(r); refresh(); }
  }

  const leave = useMutation({
    mutationFn: () => api.leaveTeam(team.id),
    onSuccess: () => { toast.success("You left the team."); refresh(); },
    onError: (e) => { toast.error(messageFor(e)); refresh(); },
    onSettled: () => setConfirm(null),
  });
  const cancel = useMutation({
    mutationFn: () => api.cancelTeam(team.id),
    onSuccess: () => { toast.success("Team cancelled."); refresh(); },
    onError: (e) => { toast.error(messageFor(e)); refresh(); },
    onSettled: () => setConfirm(null),
  });
  const mutation = confirm === "leave" ? leave : cancel;

  return (
    <Card className={`rounded-none ${team.status === "cancelled" ? "bg-muted/40" : ""}`}>
      <CardContent className="space-y-4 p-4 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 space-y-2">
            <Badge variant="outline" className={`border-0 ${team.status === "registered" ? "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-100" : "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-100"}`}>
              {teamStatusLabel(team.status)}
            </Badge>
            <h2 className="break-words pt-1 text-xl leading-tight">{team.name}</h2>
            <p className="text-sm text-muted-foreground">
              <Link to="/events/$id" params={{ id: team.event_id }} className="hover:text-primary-text hover:underline">{team.event_name}</Link> · {team.category_name}
            </p>
          </div>
          <p className="text-sm font-semibold">{team.member_count} of {team.team_size_min}{team.team_size_max !== team.team_size_min ? ` to ${team.team_size_max}` : ""} players</p>
        </div>

        {team.is_captain && team.invite_code && team.status === "forming" && <InviteCode code={team.invite_code} teamName={team.name} />}

        <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
          className="inline-flex min-h-11 items-center gap-1.5 text-sm font-medium text-muted-foreground hover:text-foreground">
          <ChevronDown className={`size-4 transition-transform ${open ? "rotate-180" : ""}`} />{open ? "Hide players" : "Show players"}
        </button>
        {open && (
          members.isPending ? <Spinner label="Loading players..." />
          : members.isError ? <ErrorState error={members.error} onRetry={() => void members.refetch()} />
          : <ul className="space-y-1.5 text-sm">
              {members.data.members.map((m) => (
                <li key={m.user_id} className="flex items-center gap-2"><span className="font-medium">{m.name}</span>{m.is_captain && <Badge variant="outline">Captain</Badge>}</li>
              ))}
            </ul>
        )}

        {actions.registerHint && <p className="text-sm text-muted-foreground">{actions.registerHint}</p>}

        {(actions.canRegister || actions.canLeave || actions.canCancel) && (
          <div className="flex flex-col gap-2 sm:flex-row [&_button]:w-full sm:[&_button]:w-auto">
            {actions.canRegister && (
              <Button className="min-h-11 rounded-none px-6 font-semibold" onClick={() => void onRegister()} disabled={register.pending}>
                {register.pending ? <Spinner label="Registering..." /> : "Register team"}
              </Button>
            )}
            {actions.canLeave && <Button variant="outline" className="min-h-11 rounded-none px-6" onClick={() => setConfirm("leave")}>Leave team</Button>}
            {actions.canCancel && <Button variant="outline" className="min-h-11 rounded-none px-6" onClick={() => setConfirm("cancel")}>Cancel team</Button>}
          </div>
        )}
      </CardContent>

      <RegistrationResultDialog result={result} onClose={() => setResult(null)} />

      <AlertDialog open={confirm !== null} onOpenChange={(o) => { if (!o && !mutation.isPending) setConfirm(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{confirm === "leave" ? "Leave this team?" : "Cancel this team?"}</AlertDialogTitle>
            <AlertDialogDescription>
              {confirm === "leave"
                ? `You will no longer be part of ${team.name}. You can rejoin with the invite code while the team is still forming.`
                : team.status === "registered"
                  ? `${team.name} is registered. Cancelling releases its place for everyone in the team and cannot be undone.`
                  : `${team.name} will be disbanded and its invite code stops working. This cannot be undone.`}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={mutation.isPending}>Keep it</AlertDialogCancel>
            <AlertDialogAction disabled={mutation.isPending} onClick={(e) => { e.preventDefault(); mutation.mutate(); }}>
              {mutation.isPending ? <Spinner label="Working..." /> : confirm === "leave" ? "Leave team" : "Cancel team"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  );
}
