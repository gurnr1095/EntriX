import { createFileRoute } from "@tanstack/react-router";
import { PlaceholderPage } from "@/components/placeholder-page";
export const Route = createFileRoute("/my/teams")({
 head: () => ({ meta: [{ title: "My teams | EntriX" }, { name: "description", content: "My teams on EntriX." }, { property: "og:title", content: "My teams | EntriX" }, { property: "og:description", content: "My teams on EntriX." }, { property: "og:type", content: "website" }, { name: "twitter:card", content: "summary_large_image" }] }),
 component: Page,
});
function Page() { return <PlaceholderPage title="My teams" kind="teams" />; }
