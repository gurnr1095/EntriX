import { CalendarDays, Ticket, Users, UserRound, Shield, ScanLine, Flag, type LucideIcon } from "lucide-react";
const icons: Record<string, LucideIcon> = { events: CalendarDays, registrations: Ticket, teams: Users, profile: UserRound, organizer: Shield, scanner: ScanLine, event: Flag };
export function PlaceholderPage({ title, kind, id }: { title: string; kind: string; id?: string }) {
  const Icon = icons[kind] ?? CalendarDays;
  return <section><div className="mb-8 flex items-end justify-between border-b border-border pb-6"><div><p className="mb-2 text-xs font-semibold uppercase text-muted-foreground">EntriX / {title}</p><h1 className="font-display text-3xl font-semibold md:text-4xl">{title}</h1></div>{id && <span className="text-sm text-muted-foreground">#{id}</span>}</div><div className="flex min-h-80 flex-col items-center justify-center text-center"><div className="mb-5 flex size-16 items-center justify-center rounded-full bg-muted"><Icon className="size-7 text-muted-foreground" strokeWidth={1.5} /></div><h2 className="font-display text-xl font-semibold">{title}</h2><p className="mt-2 text-sm text-muted-foreground">Coming soon.</p></div></section>;
}
