import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { ContactInfo, telHref } from "@/components/contact-info";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function render(contact: { name: string; email: string; phone: string }) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => { root.render(<ContactInfo contact={contact} />); });
  return host;
}
afterEach(() => { document.body.innerHTML = ""; });

describe("telHref", () => {
  it("keeps digits and a leading plus only", () => {
    expect(telHref("+91 98765-43210")).toBe("tel:+919876543210");
    expect(telHref("(011) 2345 6789")).toBe("tel:01123456789");
    expect(telHref(" 98765 43210 ")).toBe("tel:9876543210");
  });
});

describe("ContactInfo", () => {
  it("shows nothing until details are filled in", () => {
    expect(render({ name: "", email: "  ", phone: "" }).innerHTML).toBe("");
  });
  it("links the email and the phone", () => {
    const host = render({ name: "Sports Committee", email: "sports@college.edu", phone: "+91 98765 43210" });
    expect(host.textContent).toContain("Sports Committee");
    expect(host.querySelector<HTMLAnchorElement>("a[href^='mailto:']")?.getAttribute("href")).toBe("mailto:sports@college.edu");
    expect(host.querySelector<HTMLAnchorElement>("a[href^='tel:']")?.getAttribute("href")).toBe("tel:+919876543210");
  });
  it("hides the fields that are empty", () => {
    const host = render({ name: "", email: "a@b.co", phone: "" });
    expect(host.querySelector("a[href^='tel:']")).toBeNull();
    expect(host.textContent).toContain("a@b.co");
  });
});
