import { Link } from "@tanstack/react-router";
import { CheckCircle2, Clock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { RegistrationResult } from "@/types";

export function RegistrationResultDialog({ result, onClose }: { result: RegistrationResult | null; onClose: () => void }) {
  const waitlisted = result?.status === "waitlisted";
  return (
    <Dialog open={result !== null} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent>
        <DialogHeader>
          <div className={`mx-auto mb-2 flex size-14 items-center justify-center rounded-full ${waitlisted ? "bg-amber-100 dark:bg-amber-900/40" : "bg-emerald-100 dark:bg-emerald-900/40"}`}>
            {waitlisted ? <Clock className="size-7 text-amber-700 dark:text-amber-200" /> : <CheckCircle2 className="size-7 text-emerald-700 dark:text-emerald-200" />}
          </div>
          <DialogTitle className="text-center">{waitlisted ? "You are on the waitlist" : "You are in!"}</DialogTitle>
          <DialogDescription className="text-center">
            {waitlisted
              ? `You are number ${result?.waitlist_position ?? "?"} on the waitlist. If a seat opens we confirm you automatically and email you.`
              : "Your spot is confirmed. We emailed you the details and your QR code."}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="sm:justify-center">
          <Button asChild onClick={onClose}><Link to="/my/registrations">View my registrations</Link></Button>
          <Button variant="outline" onClick={onClose}>Close</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
