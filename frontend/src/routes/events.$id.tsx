import { createFileRoute } from "@tanstack/react-router";
import { PlaceholderPage } from "@/components/placeholder-page";
export const Route = createFileRoute("/events/$id")({
 head: () => ({ meta: [{ title: "Event | EntriX" }, { name: "description", content: "Event on EntriX." }, { property: "og:title", content: "Event | EntriX" }, { property: "og:description", content: "Event on EntriX." }, { property: "og:type", content: "website" }, { name: "twitter:card", content: "summary_large_image" }] }),
 component: Page,
});
function Page() { const { id } = Route.useParams(); return <PlaceholderPage title="Event" kind="event" id={id} />; }
