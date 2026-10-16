import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { CameraOff, CheckCircle2, RefreshCw, TriangleAlert, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/page-state";
import { api } from "@/lib/api";
import { describeCameraError, extractToken, outcomeFromError, outcomeFromResult, ScanGate, type ScanOutcome } from "@/lib/scan";

const READER_ID = "entrix-qr-reader";
const BANNER_MS = 4000;

type CameraState = "starting" | "scanning" | "unavailable";

const TONE = {
  success: { cls: "bg-emerald-600 text-white", Icon: CheckCircle2 },
  already: { cls: "bg-amber-500 text-black", Icon: TriangleAlert },
  error: { cls: "bg-red-600 text-white", Icon: XCircle },
} as const;

/** Camera scanner with a manual fallback. Every scan goes through ScanGate and api.checkIn. */
export function QrScanner({ eventId, initialToken, onInitialTokenUsed }: { eventId: string; initialToken?: string | null; onInitialTokenUsed?: () => void }) {
  const [camera, setCamera] = useState<CameraState>("starting");
  const [outcome, setOutcome] = useState<ScanOutcome | null>(null);
  const [count, setCount] = useState(0);
  const [manual, setManual] = useState("");
  const [pending, setPending] = useState(false);
  const [cameraIndex, setCameraIndex] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [cameraReason, setCameraReason] = useState<string | null>(null);
  const [cameraCount, setCameraCount] = useState(1);
  const gate = useRef(new ScanGate());
  const hideTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const eventRef = useRef(eventId);
  eventRef.current = eventId;

  const show = useCallback((o: ScanOutcome) => {
    setOutcome(o);
    clearTimeout(hideTimer.current);
    hideTimer.current = setTimeout(() => setOutcome(null), BANNER_MS);
    try { navigator.vibrate?.(o.tone === "success" ? 80 : [60, 40, 60]); } catch { /* not supported */ }
  }, []);

  const submit = useCallback(async (text: string) => {
    if (!gate.current.begin(text)) return;
    setPending(true);
    try {
      const result = await api.checkIn(eventRef.current, extractToken(text));
      const o = outcomeFromResult(result);
      if (o.tone === "success") setCount((c) => c + 1);
      show(o);
    } catch (e) {
      show(outcomeFromError(e));
    } finally {
      gate.current.done();
      setPending(false);
    }
  }, [show]);

  // Start and stop the camera. html5-qrcode touches the DOM, so it is loaded only in the browser.
  useEffect(() => {
    let stopped = false;
    let started = false;
    let scanner: { stop: () => Promise<void>; clear: () => void; isScanning?: boolean } | null = null;
    setCamera("starting");
    (async () => {
      try {
        const { Html5Qrcode } = await import("html5-qrcode");
        const instance = new Html5Qrcode(READER_ID, { verbose: false });
        scanner = instance;
        // The first start asks the browser for the rear camera (laptops fall back to their webcam).
        // "Switch camera" then picks a specific device by id.
        let source: string | { facingMode: string } = { facingMode: "environment" };
        if (cameraIndex > 0) {
          const cameras = await Html5Qrcode.getCameras();
          const chosen = cameras[cameraIndex % Math.max(cameras.length, 1)];
          if (chosen) source = chosen.id;
        }
        await instance.start(
          source,
          { fps: 10, qrbox: (w: number, h: number) => { const s = Math.floor(Math.min(w, h) * 0.8); return { width: s, height: s }; } },
          (text: string) => { void submit(text); },
          () => { /* no code in this frame */ },
        );
        started = true;
        if (stopped) { try { await instance.stop(); } catch { /* already stopped */ } return; }
        setCamera("scanning");
        setCameraReason(null);
        // Permission is granted now, so the device list is available for the Switch button.
        Html5Qrcode.getCameras().then((c) => { if (!stopped) setCameraCount(c.length || 1); }, () => {});
      } catch (e) {
        console.error("Scanner camera failed:", e);
        if (!stopped) { setCamera("unavailable"); setCameraReason(describeCameraError(e)); }
      }
    })();
    return () => {
      stopped = true;
      const s = scanner;
      if (!s) return;
      // stop() throws straight away if the camera never started, and an error in a cleanup would
      // blank the whole page, so only stop what is running and swallow anything else.
      try {
        if (started) void s.stop().then(() => s.clear()).catch(() => {});
        else s.clear();
      } catch { /* nothing to release */ }
    };
  }, [cameraIndex, attempt, submit]);

  // A scan link opened from the phone's own camera app arrives with the token already in the address.
  const usedInitial = useRef(false);
  useEffect(() => {
    if (!initialToken || usedInitial.current) return;
    usedInitial.current = true;
    void submit(initialToken).finally(() => onInitialTokenUsed?.());
  }, [initialToken, submit, onInitialTokenUsed]);

  useEffect(() => () => clearTimeout(hideTimer.current), []);

  async function onManual(e: FormEvent) {
    e.preventDefault();
    const text = manual.trim();
    if (!text) return;
    await submit(text);
    setManual("");
  }

  return (
    <div className="space-y-5">
      <div
        role="status"
        aria-live="assertive"
        className={`min-h-24 rounded-xl p-4 text-center ${outcome ? TONE[outcome.tone].cls : "bg-muted text-muted-foreground"}`}
      >
        {outcome ? (
          <div className="flex flex-col items-center gap-1">
            {(() => { const I = TONE[outcome.tone].Icon; return <I className="size-8" aria-hidden />; })()}
            <p className="font-display text-2xl font-extrabold">{outcome.title}</p>
            <p className="text-base font-medium">{outcome.detail}</p>
          </div>
        ) : (
          <p className="flex h-16 items-center justify-center gap-2 text-sm">
            {pending ? <Spinner label="Checking..." /> : camera === "scanning" ? "Point the camera at a QR code" : "Waiting for the camera"}
          </p>
        )}
      </div>

      <div className="overflow-hidden rounded-xl bg-black">
        <div id={READER_ID} className="min-h-64 w-full" />
        {camera === "starting" && <p className="p-4 text-center text-sm text-white"><Spinner label="Starting camera..." /></p>}
        {camera === "unavailable" && (
          <div className="flex flex-col items-center gap-2 p-6 text-center text-white">
            <CameraOff className="size-8" aria-hidden />
            <p className="font-semibold">The camera is not available</p>
            <p className="max-w-xs text-sm text-white/80">{cameraReason ?? "The camera could not start."}</p>
            <p className="max-w-xs text-sm text-white/80">You can still check people in with the box below.</p>
            <Button variant="secondary" className="mt-2 min-h-11 rounded-full px-5" onClick={() => setAttempt((a) => a + 1)}>Try again</Button>
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm font-semibold">Checked in this session: {count}</p>
        {cameraCount > 1 && (
          <Button variant="outline" className="min-h-11 rounded-full px-5" onClick={() => setCameraIndex((i) => i + 1)}>
            <RefreshCw />Switch camera
          </Button>
        )}
      </div>

      <form onSubmit={onManual} className="space-y-2 rounded-xl bg-muted/50 p-4">
        <Label htmlFor="manual-token">Enter a code by hand</Label>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input id="manual-token" value={manual} onChange={(e) => setManual(e.target.value)} autoComplete="off" autoCapitalize="off" spellCheck={false} placeholder="Paste the code here" />
          <Button type="submit" className="min-h-11 rounded-full px-6 font-semibold" disabled={pending || !manual.trim()}>Check in</Button>
        </div>
      </form>
    </div>
  );
}
