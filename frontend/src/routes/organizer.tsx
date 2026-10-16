import { createFileRoute } from "@tanstack/react-router";
import { PlaceholderPage } from "@/components/placeholder-page";
export const Route = createFileRoute("/organizer")({
 head: () => ({ meta: [{ title: "Organizer | EntriX" }, { name: "description", content: "Organizer on EntriX." }, { property: "og:title", content: "Organizer | EntriX" }, { property: "og:description", content: "Organizer on EntriX." }, { property: "og:type", content: "website" }, { name: "twitter:card", content: "summary_large_image" }] }),
 component: Page,
});
function Page() { return <PlaceholderPage title="Organizer" kind="organizer" />; }
