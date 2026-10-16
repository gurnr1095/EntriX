import { useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { CheckCircle2, WifiOff } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Spinner } from "@/components/page-state";
import { api } from "@/lib/api";
import { messageFor } from "@/lib/errors";
import { getCachedQr, setCachedQr } from "@/lib/qr-cache";
import type { MyRegistration } from "@/types";

interface Props {
  registration: MyRegistration | null;
  participantName: string | undefined;
  onClose: () => void;
}

/** A big white QR a volunteer can scan from an arm's length. Works offline once opened once. */
export function QrDialog({ registration, participantName, onClose }: Props) {
  const id = registration?.registration_id ?? null;
  const [token, setToken] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    setToken(getCachedQr(id)); // show the saved code at once, then refresh
    setError(null);
    api.qr(id).then(
      (r) => {
        if (cancelled) return;
        setToken(r.token);
        setCachedQr(id, r.token);
      },
      (e: unknown) => { if (!cancelled) setError(e); },
    );
    return () => { cancelled = true; };
  }, [id]);

  const checkedIn = registration?.status === "checked_in";

  return (
    <Dialog open={registration !== null} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle className="text-center">{registration?.event_name}</DialogTitle>
          <DialogDescription className="text-center">
            {registration?.category_name}{participantName ? ` · ${participantName}` : ""}
          </DialogDescription>
        </DialogHeader>

        {checkedIn && (
          <p role="status" className="flex items-center justify-center gap-2 rounded-md bg-emerald-100 px-3 py-2 text-sm font-semibold text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-100">
            <CheckCircle2 className="size-4" />Checked in
          </p>
        )}

        <div className="mx-auto flex size-72 max-w-full items-center justify-center rounded-xl bg-white p-4">
          {token ? (
            <QRCodeSVG value={token} size={256} level="H" bgColor="#ffffff" fgColor="#000000" title="Check-in QR code" className="h-full w-full" />
          ) : error ? (
            <p role="alert" className="text-center text-sm text-neutral-700">{messageFor(error)}</p>
          ) : (
            <span className="text-neutral-700"><Spinner label="Loading..." /></span>
          )}
        </div>

        {token && error != null && (
          <p className="flex items-center justify-center gap-2 text-xs text-muted-foreground">
            <WifiOff className="size-3.5" />No connection. Showing your saved code.
          </p>
        )}
        <p className="text-center text-xs text-muted-foreground">Show this code to the volunteer at the entrance.</p>
      </DialogContent>
    </Dialog>
  );
}
