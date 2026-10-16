import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/page-state";
import { messageFor } from "@/lib/errors";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  label: string;
  submitLabel: string;
  /** Normalise before sending (e.g. upper-case an invite code). */
  transform?: (value: string) => string;
  onSubmit: (value: string) => Promise<void>;
  maxLength?: number;
}

/** One text field, a submit button that is disabled while pending, and the error shown inline. */
export function TextPromptDialog(p: Props) {
  const [value, setValue] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const text = (p.transform ? p.transform(value) : value).trim();
    if (!text || pending) return;
    setPending(true);
    setError(null);
    try {
      await p.onSubmit(text);
      setValue("");
      p.onOpenChange(false);
    } catch (err) {
      setError(err);
    } finally {
      setPending(false);
    }
  }

  return (
    <Dialog open={p.open} onOpenChange={(o) => { if (!pending) { setError(null); p.onOpenChange(o); } }}>
      <DialogContent>
        <form onSubmit={submit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>{p.title}</DialogTitle>
            <DialogDescription>{p.description}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="prompt-field">{p.label}</Label>
            <Input id="prompt-field" value={value} onChange={(e) => setValue(e.target.value)}
              maxLength={p.maxLength ?? 80} autoFocus autoComplete="off" aria-invalid={!!error} />
            {error != null && <p role="alert" className="text-sm text-destructive">{messageFor(error)}</p>}
          </div>
          <DialogFooter>
            <Button type="submit" disabled={pending || !value.trim()}>
              {pending ? <Spinner label="Working..." /> : p.submitLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
