import { createFileRoute } from "@tanstack/react-router";
import { PlaceholderPage } from "@/components/placeholder-page";
export const Route = createFileRoute("/scan")({
 head: () => ({ meta: [{ title: "Scan | EntriX" }, { name: "description", content: "Scan on EntriX." }, { property: "og:title", content: "Scan | EntriX" }, { property: "og:description", content: "Scan on EntriX." }, { property: "og:type", content: "website" }, { name: "twitter:card", content: "summary_large_image" }] }),
 component: Page,
});
function Page() { return <PlaceholderPage title="Scan" kind="scanner" />; }
