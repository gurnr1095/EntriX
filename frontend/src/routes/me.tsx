import { createFileRoute } from "@tanstack/react-router";
import { PlaceholderPage } from "@/components/placeholder-page";
export const Route = createFileRoute("/me")({
 head: () => ({ meta: [{ title: "My profile | EntriX" }, { name: "description", content: "My profile on EntriX." }, { property: "og:title", content: "My profile | EntriX" }, { property: "og:description", content: "My profile on EntriX." }, { property: "og:type", content: "website" }, { name: "twitter:card", content: "summary_large_image" }] }),
 component: Page,
});
function Page() { return <PlaceholderPage title="My profile" kind="profile" />; }
