import { createFileRoute } from "@tanstack/react-router";
import { PlaceholderPage } from "@/components/placeholder-page";
export const Route = createFileRoute("/organizer_/events/$id")({
 head: () => ({ meta: [{ title: "Manage event | EntriX" }, { name: "description", content: "Manage event on EntriX." }, { property: "og:title", content: "Manage event | EntriX" }, { property: "og:description", content: "Manage event on EntriX." }, { property: "og:type", content: "website" }, { name: "twitter:card", content: "summary_large_image" }] }),
 component: Page,
});
function Page() { const { id } = Route.useParams(); return <PlaceholderPage title="Manage event" kind="organizer" id={id} />; }
