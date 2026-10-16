import { useEffect, useState } from "react";
import { SignInButton, useAuth } from "@clerk/clerk-react";
import { useNavigate } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Spinner } from "@/components/page-state";
import { RegistrationResultDialog } from "@/components/registration-result-dialog";
import { TextPromptDialog } from "@/components/text-prompt-dialog";
import { api } from "@/lib/api";
import { ApiError, messageFor } from "@/lib/errors";
import { categoryAction, seatsLabel, type RegWindow } from "@/lib/format";
import { useIdempotentAction } from "@/lib/idempotency";
import { keys } from "@/lib/queries";
import type { Category, RegistrationResult } from "@/types";

/** Counts down a 429's Retry-After so the button re-enables itself. */
function useCooldown() {
  const [until, setUntil] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (until <= Date.now()) return;
    const t = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(t);
  }, [until]);
  const remaining = Math.max(0, Math.ceil((until - now) / 1000));
  return {
    remaining,
    start: (seconds: number) => {
      setNow(Date.now());
      setUntil(Date.now() + seconds * 1000);
    },
  };
}

export function CategoryCard({ category, window }: { category: Category; window: RegWindow }) {
  const { isSignedIn } = useAuth();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [result, setResult] = useState<RegistrationResult | null>(null);
  const [teamDialog, setTeamDialog] = useState<"create" | "join" | null>(null);
  const cooldown = useCooldown();

  const action = categoryAction(category, window);
  const register = useIdempotentAction((key) => api.register(category.id, key));

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: keys.event(category.event_id) });
    void qc.invalidateQueries({ queryKey: keys.myRegistrations });
  };

  async function onRegister() {
    const r = await register.fire();
    if (r) {
      setResult(r);
      refresh();
    }
  }

  // Report what went wrong, once per failure.
  const { error, clearError } = register;
  useEffect(() => {
    if (error == null) return;
    if (error instanceof ApiError && error.status === 429) cooldown.start(error.retryAfter ?? 30);
    const unknownOutcome = !(error instanceof ApiError) || error.status === 0 || error.status >= 500;
    if (unknownOutcome) {
      toast.error("We could not confirm your registration. Tap Register again: you will not be registered twice.");
    } else {
      toast.error(messageFor(error));
      refresh(); // seats or window changed: show the truth
    }
    clearError();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [error]);

  const pct = Math.min(100, Math.round((category.confirmed_count / category.capacity) * 100));
  const cooling = cooldown.remaining > 0;
  const level = pct >= 90 ? "urgent" : pct >= 65 ? "warm" : "calm";
  const barCls = level === "urgent" ? "bg-destructive/15 [&>div]:bg-destructive" : level === "warm" ? "bg-warning/20 [&>div]:bg-warning" : "bg-success/15 [&>div]:bg-success";
  const muted = action === "closed" || action === "full" || action === "not_open_yet";

  return (
    <Card className={`overflow-hidden rounded-xl shadow-card transition-shadow duration-200 hover:shadow-lift ${muted ? "bg-muted/40" : ""}`}>
      <CardContent className="flex flex-col gap-5 p-4 sm:flex-row sm:items-center sm:justify-between sm:gap-8 sm:p-6">
        <div className="min-w-0 flex-1 space-y-3">
          <div>
            <div className="flex flex-wrap items-center gap-2"><h3 className="break-words font-display text-lg font-bold">{category.name}</h3>{action === "full" && <span className="rounded-full bg-destructive/10 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-destructive">Full</span>}{action === "waitlist" && <span className="rounded-full bg-warning-soft px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-warning-foreground">Waitlist</span>}{action === "closed" && <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-muted-foreground">Closed</span>}</div>
            <p className="text-sm text-muted-foreground">
              <span className="capitalize">{category.sport.replace(/-/g, " ")}</span> ·{" "}
              {category.participation === "team" ? `team of ${category.team_size_min} to ${category.team_size_max}` : "individual"}
            </p>
          </div>
          <Progress value={pct} aria-label={`${pct}% full`} className={`h-2.5 ${barCls} [&>div]:duration-500`} />
          <p className={`text-sm font-semibold ${level === "urgent" ? "text-destructive" : level === "warm" ? "text-warning-foreground" : "text-success-foreground"}`}>
            {seatsLabel(category)}
            {category.seats_left <= 0 && category.waitlist_enabled ? " · waitlist open" : ""}
          </p>
        </div>

        <div className="flex shrink-0 flex-col gap-2 sm:items-end [&_button]:w-full sm:[&_button]:w-auto">
          {action === "not_open_yet" && <Button disabled variant="secondary" className="min-h-11 rounded-full">Registration not open yet</Button>}
          {action === "closed" && <Button disabled variant="secondary" className="min-h-11 rounded-full">Registration closed</Button>}
          {action === "full" && <Button disabled variant="secondary" className="min-h-11 rounded-full">Full</Button>}

          {(action === "register" || action === "waitlist") &&
            (isSignedIn ? (
              <Button onClick={onRegister} disabled={register.pending || cooling} className="min-h-11 rounded-full px-6 font-semibold shadow-lift">
                {register.pending ? (
                  <Spinner label="Registering..." />
                ) : cooling ? (
                  `Try again in ${cooldown.remaining}s`
                ) : action === "waitlist" ? (
                  "Join waitlist"
                ) : (
                  "Register"
                )}
              </Button>
            ) : (
              <SignInButton mode="modal"><Button className="min-h-11 rounded-full px-6 font-semibold shadow-lift">Sign in to register</Button></SignInButton>
            ))}

          {action === "team" &&
            (isSignedIn ? (
              <div className="flex flex-col gap-2 sm:flex-row">
                <Button className="min-h-11 rounded-full px-6 font-semibold shadow-lift" onClick={() => setTeamDialog("create")}>Create team</Button>
                <Button className="min-h-11 rounded-full px-6 font-semibold" variant="outline" onClick={() => setTeamDialog("join")}>Join with code</Button>
              </div>
            ) : (
              <SignInButton mode="modal"><Button className="min-h-11 rounded-full px-6 font-semibold shadow-lift">Sign in to join</Button></SignInButton>
            ))}
        </div>
      </CardContent>

      <RegistrationResultDialog result={result} onClose={() => setResult(null)} />

      <TextPromptDialog
        open={teamDialog === "create"}
        onOpenChange={(o) => setTeamDialog(o ? "create" : null)}
        title="Create a team"
        description={`You become the captain of a ${category.name} team. You will get an invite code to share.`}
        label="Team name"
        submitLabel="Create team"
        onSubmit={async (name) => {
          await api.createTeam(category.id, name);
          void qc.invalidateQueries({ queryKey: keys.myTeams });
          toast.success("Team created. Share the invite code with your players.");
          await navigate({ to: "/my/teams" });
        }}
      />
      <TextPromptDialog
        open={teamDialog === "join"}
        onOpenChange={(o) => setTeamDialog(o ? "join" : null)}
        title="Join a team"
        description="Enter the invite code your captain shared."
        label="Invite code"
        submitLabel="Join team"
        maxLength={20}
        transform={(v) => v.replace(/\s+/g, "").toUpperCase()}
        onSubmit={async (code) => {
          await api.joinTeam(code);
          void qc.invalidateQueries({ queryKey: keys.myTeams });
          toast.success("You joined the team.");
          await navigate({ to: "/my/teams" });
        }}
      />
    </Card>
  );
}
