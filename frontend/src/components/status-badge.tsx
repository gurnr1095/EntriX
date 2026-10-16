import { Badge } from "@/components/ui/badge";
import type { RegStatus } from "@/types";
import type { RegWindow } from "@/lib/format";

const STATUS: Record<RegStatus, { label: string; cls: string }> = {
  confirmed: { label: "Confirmed", cls: "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-100" },
  waitlisted: { label: "Waitlisted", cls: "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-100" },
  cancelled: { label: "Cancelled", cls: "bg-muted text-muted-foreground" },
  checked_in: { label: "Checked in", cls: "bg-sky-100 text-sky-900 dark:bg-sky-900/40 dark:text-sky-100" },
};

export function RegStatusBadge({ status }: { status: RegStatus }) {
  const s = STATUS[status];
  return <Badge variant="outline" className={`border-0 ${s.cls}`}>{s.label}</Badge>;
}

export function WindowBadge({ window, opensLabel }: { window: RegWindow; opensLabel: string }) {
  if (window === "open") return <Badge className="border-0 bg-emerald-100 text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-100">Registration open</Badge>;
  if (window === "upcoming") return <Badge variant="outline">{opensLabel}</Badge>;
  return <Badge variant="outline" className="text-muted-foreground">Registration closed</Badge>;
}
