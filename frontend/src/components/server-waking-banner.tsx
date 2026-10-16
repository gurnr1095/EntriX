import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { onServerSlow } from "@/lib/api";

/** Free hosting sleeps when idle and takes ~35 s to wake. Say so instead of showing a blank page. */
export function ServerWakingBanner() {
  const [slow, setSlow] = useState(false);
  useEffect(() => onServerSlow(setSlow), []);
  if (!slow) return null;
  return (
    <div role="status" aria-live="polite" className="flex items-center justify-center gap-2 bg-amber-100 px-4 py-2 text-sm text-amber-950 dark:bg-amber-900 dark:text-amber-50">
      <Loader2 className="size-4 animate-spin" />
      Waking the server, this can take up to 40 seconds...
    </div>
  );
}
