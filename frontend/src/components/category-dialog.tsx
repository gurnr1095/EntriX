import { useEffect, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Spinner } from "@/components/page-state";
import { api } from "@/lib/api";
import { messageFor } from "@/lib/errors";
import { validateCategory, type CategoryValues } from "@/lib/organizer";
import type { Category, CategoryCreate, CategoryPatch } from "@/types";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  eventId: string;
  /** Present when editing. Sport type and team sizes cannot change after creation. */
  category?: Category | undefined;
  onSaved: () => void;
}

const blank: CategoryValues = { name: "", sport: "", participation: "individual", teamMin: "2", teamMax: "5", capacity: "32" };

export function CategoryDialog({ open, onOpenChange, eventId, category, onSaved }: Props) {
  const editing = category !== undefined;
  const [v, setV] = useState<CategoryValues>(blank);
  const [waitlist, setWaitlist] = useState(true);
  const [problem, setProblem] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const qc = useQueryClient();

  useEffect(() => {
    if (!open) return;
    setProblem(null);
    if (category) {
      setV({
        name: category.name, sport: category.sport, participation: category.participation,
        teamMin: String(category.team_size_min ?? ""), teamMax: String(category.team_size_max ?? ""),
        capacity: String(category.capacity),
      });
      setWaitlist(category.waitlist_enabled);
    } else {
      setV(blank);
      setWaitlist(true);
    }
  }, [open, category]);

  const set = (k: keyof CategoryValues) => (value: string) => setV((s) => ({ ...s, [k]: value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (pending) return;
    const bad = validateCategory(v);
    if (bad) { setProblem(bad); return; }
    setProblem(null);
    setPending(true);
    try {
      if (category) {
        const patch: CategoryPatch = {};
        if (v.name.trim() !== category.name) patch.name = v.name.trim();
        if (v.sport.trim() !== category.sport) patch.sport = v.sport.trim();
        if (Number(v.capacity) !== category.capacity) patch.capacity = Number(v.capacity);
        if (waitlist !== category.waitlist_enabled) patch.waitlist_enabled = waitlist;
        if (Object.keys(patch).length > 0) await api.patchCategory(category.id, patch);
      } else {
        const body: CategoryCreate = {
          name: v.name.trim(), sport: v.sport.trim().toLowerCase().replace(/\s+/g, "-"),
          participation: v.participation, capacity: Number(v.capacity), waitlist_enabled: waitlist,
          ...(v.participation === "team" ? { team_size_min: Number(v.teamMin), team_size_max: Number(v.teamMax) } : {}),
        };
        await api.createCategory(eventId, body);
      }
      void qc.invalidateQueries({ queryKey: ["org-event", eventId] });
      void qc.invalidateQueries({ queryKey: ["org-stats", eventId] });
      void qc.invalidateQueries({ queryKey: ["event", eventId] });
      toast.success(editing ? "Category updated." : "Category added.");
      onSaved();
      onOpenChange(false);
    } catch (err) {
      setProblem(messageFor(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!pending) onOpenChange(o); }}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto">
        <form onSubmit={submit} className="space-y-5" noValidate>
          <DialogHeader>
            <DialogTitle>{editing ? "Edit category" : "Add a category"}</DialogTitle>
            <DialogDescription>
              {editing
                ? "Raising the capacity moves people from the waitlist into the new seats straight away. It cannot go below the number already confirmed."
                : "One sport or competition within the event, with its own seats."}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="cat-name">Name</Label>
            <Input id="cat-name" value={v.name} onChange={(e) => set("name")(e.target.value)} placeholder="Table Tennis Singles" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="cat-sport">Sport</Label>
            <Input id="cat-sport" value={v.sport} onChange={(e) => set("sport")(e.target.value)} placeholder="table-tennis" />
          </div>
          {!editing && (
            <div className="space-y-2">
              <Label htmlFor="cat-kind">Played as</Label>
              <Select value={v.participation} onValueChange={(x) => set("participation")(x)}>
                <SelectTrigger id="cat-kind" className="min-h-11"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="individual">Individual</SelectItem>
                  <SelectItem value="team">Team</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}
          {!editing && v.participation === "team" && (
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="cat-min">Smallest team</Label>
                <Input id="cat-min" inputMode="numeric" value={v.teamMin} onChange={(e) => set("teamMin")(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="cat-max">Largest team</Label>
                <Input id="cat-max" inputMode="numeric" value={v.teamMax} onChange={(e) => set("teamMax")(e.target.value)} />
              </div>
            </div>
          )}
          <div className="space-y-2">
            <Label htmlFor="cat-cap">{v.participation === "team" ? "Number of teams allowed" : "Seats"}</Label>
            <Input id="cat-cap" inputMode="numeric" value={v.capacity} onChange={(e) => set("capacity")(e.target.value)} />
          </div>
          <div className="flex items-center justify-between gap-4 rounded-none bg-muted/50 p-4">
            <div>
              <Label htmlFor="cat-wl">Waitlist</Label>
              <p className="text-xs text-muted-foreground">When full, let people queue for a seat.</p>
            </div>
            <Switch id="cat-wl" checked={waitlist} onCheckedChange={setWaitlist} />
          </div>
          {problem && <p role="alert" className="text-sm font-medium text-destructive">{problem}</p>}
          <Button type="submit" className="min-h-11 w-full rounded-none font-semibold" disabled={pending}>
            {pending ? <Spinner label="Saving..." /> : editing ? "Save changes" : "Add category"}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
