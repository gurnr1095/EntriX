import { createFileRoute } from "@tanstack/react-router";
import { CalendarDays, ArrowUpRight } from "lucide-react";
import track from "@/assets/track.jpg";
export const Route = createFileRoute("/")({
  head: () => ({ meta: [{ title: "Events | EntriX" }, { name: "description", content: "Sports events on EntriX." }, { property: "og:title", content: "Events | EntriX" }, { property: "og:description", content: "Sports events on EntriX." }, { property: "og:type", content: "website" }, { name: "twitter:card", content: "summary_large_image" }] }),
  component: Index,
});
function Index() {
  return <><div className="mb-7 flex items-end justify-between"><div><p className="mb-3 text-xs font-semibold uppercase text-muted-foreground">The starting line</p><h1 className="font-display text-4xl font-semibold">Events</h1><p className="mt-3 text-sm text-muted-foreground">Your next game starts here.</p></div><ArrowUpRight className="mb-1 hidden size-9 text-primary sm:block" strokeWidth={1.3} /></div>
    <div className="relative h-44 overflow-hidden rounded-md md:h-60"><img src={track} alt="A sunlit athletics track surrounding a green playing field" width={1536} height={512} className="h-full w-full object-cover" /><span className="absolute bottom-5 left-5 flex items-center gap-2 rounded-sm bg-background px-3 py-2 text-xs font-medium"><span className="size-1.5 rounded-full bg-primary" />Every sport. One starting line.</span></div>
    <section className="mt-9"><div className="flex items-center justify-between border-b border-border pb-4"><h2 className="font-display text-lg font-semibold">Upcoming events</h2><span className="text-xs text-muted-foreground">0 events</span></div><div className="flex min-h-64 flex-col items-center justify-center py-10 text-center"><span className="mb-5 flex size-14 items-center justify-center rounded-full bg-muted"><CalendarDays className="size-6 text-muted-foreground" strokeWidth={1.5} /></span><h3 className="font-display text-lg font-semibold">No events yet</h3><p className="mt-2 text-sm text-muted-foreground">The next starting line is on its way.</p></div></section></>;
}
