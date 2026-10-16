import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Spinner } from "@/components/page-state";
import { messageFor } from "@/lib/errors";
import { blankToNull } from "@/lib/registration";
import { isoToLocal, localToIso, SLUG_PATTERN, slugify, validateEventTimes } from "@/lib/organizer";
import type { EventOut } from "@/types";

export interface EventFormValues {
  slug: string;
  name: string;
  description: string | null;
  venue: string | null;
  starts_at: string; // UTC ISO
  ends_at: string;
  reg_opens_at: string;
  reg_closes_at: string;
}

interface Props {
  initial?: EventOut;
  /** A slug can be chosen only when creating; it is part of the event's identity afterwards. */
  mode: "create" | "edit";
  submitLabel: string;
  onSubmit: (values: EventFormValues) => Promise<void>;
}

const fromEvent = (e?: EventOut) => ({
  name: e?.name ?? "",
  slug: e?.slug ?? "",
  description: e?.description ?? "",
  venue: e?.venue ?? "",
  starts: e ? isoToLocal(e.starts_at) : "",
  ends: e ? isoToLocal(e.ends_at) : "",
  opens: e ? isoToLocal(e.reg_opens_at) : "",
  closes: e ? isoToLocal(e.reg_closes_at) : "",
});

export function EventForm({ initial, mode, submitLabel, onSubmit }: Props) {
  const [v, setV] = useState(fromEvent(initial));
  const [slugTouched, setSlugTouched] = useState(mode === "edit");
  const [problem, setProblem] = useState<string | null>(null);
  const [serverError, setServerError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);

  const set = (k: keyof typeof v) => (value: string) => setV((s) => ({ ...s, [k]: value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (pending) return;
    setServerError(null);
    if (!v.name.trim()) return setProblem("Give the event a name.");
    if (!SLUG_PATTERN.test(v.slug)) return setProblem("The web address may only use lowercase letters, numbers and single hyphens.");
    const times = validateEventTimes({ starts: v.starts, ends: v.ends, opens: v.opens, closes: v.closes });
    if (times) return setProblem(times);
    setProblem(null);
    setPending(true);
    try {
      await onSubmit({
        slug: v.slug,
        name: v.name.trim(),
        description: blankToNull(v.description),
        venue: blankToNull(v.venue),
        starts_at: localToIso(v.starts),
        ends_at: localToIso(v.ends),
        reg_opens_at: localToIso(v.opens),
        reg_closes_at: localToIso(v.closes),
      });
    } catch (err) {
      setServerError(err);
    } finally {
      setPending(false);
    }
  }

  const shown = problem ?? (serverError != null ? messageFor(serverError) : null);

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      <div className="space-y-2">
        <Label htmlFor="ev-name">Event name</Label>
        <Input id="ev-name" value={v.name} maxLength={120}
          onChange={(e) => { set("name")(e.target.value); if (!slugTouched) set("slug")(slugify(e.target.value)); }} />
      </div>
      {mode === "create" && (
        <div className="space-y-2">
          <Label htmlFor="ev-slug">Web address</Label>
          <Input id="ev-slug" value={v.slug} autoCapitalize="off" spellCheck={false}
            onChange={(e) => { setSlugTouched(true); set("slug")(e.target.value.toLowerCase()); }} />
          <p className="text-xs text-muted-foreground">Letters, numbers and hyphens. It cannot be changed later.</p>
        </div>
      )}
      <div className="grid gap-5 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="ev-venue">Venue</Label>
          <Input id="ev-venue" value={v.venue} onChange={(e) => set("venue")(e.target.value)} />
        </div>
      </div>
      <div className="space-y-2">
        <Label htmlFor="ev-desc">Description</Label>
        <Textarea id="ev-desc" rows={4} value={v.description} onChange={(e) => set("description")(e.target.value)} />
      </div>
      <div className="grid gap-5 sm:grid-cols-2">
        {([
          ["starts", "Event starts"], ["ends", "Event ends"],
          ["opens", "Registration opens"], ["closes", "Registration closes"],
        ] as const).map(([key, label]) => (
          <div key={key} className="space-y-2">
            <Label htmlFor={`ev-${key}`}>{label}</Label>
            <Input id={`ev-${key}`} type="datetime-local" value={v[key]} onChange={(e) => set(key)(e.target.value)} />
          </div>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">Times are in your local time zone.</p>
      {shown && <p role="alert" className="text-sm font-medium text-destructive">{shown}</p>}
      <Button type="submit" className="min-h-11 rounded-none px-6 font-semibold" disabled={pending}>
        {pending ? <Spinner label="Saving..." /> : submitLabel}
      </Button>
    </form>
  );
}
