import { createFileRoute } from "@tanstack/react-router";
import { PlaceholderPage } from "@/components/placeholder-page";
export const Route = createFileRoute("/my/registrations")({
 head: () => ({ meta: [{ title: "My registrations | EntriX" }, { name: "description", content: "My registrations on EntriX." }, { property: "og:title", content: "My registrations | EntriX" }, { property: "og:description", content: "My registrations on EntriX." }, { property: "og:type", content: "website" }, { name: "twitter:card", content: "summary_large_image" }] }),
 component: Page,
});
function Page() { return <PlaceholderPage title="My registrations" kind="registrations" />; }
