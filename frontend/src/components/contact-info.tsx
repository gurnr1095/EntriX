import { Mail, Phone, UserRound } from "lucide-react";
import type { ContactDetails } from "@/config";

/** A phone number as a tel: link: keep digits and a leading plus, drop spaces, dashes and brackets. */
export function telHref(phone: string): string {
  const cleaned = phone.trim().replace(/(?!^\+)[^\d]/g, "");
  return `tel:${cleaned}`;
}

/** Whoever organizes the events, so people can ask before they register. Renders nothing without details. */
export function ContactInfo({ contact }: { contact: ContactDetails }) {
  const name = contact.name.trim();
  const email = contact.email.trim();
  const phone = contact.phone.trim();
  if (!name && !email && !phone) return null;

  return (
    <div className="space-y-1 text-base">
            <ul className="flex flex-col gap-x-6 gap-y-0.5 md:flex-row md:flex-wrap" aria-label="Contact the organizers">
        {name && <li className="inline-flex items-center gap-2"><UserRound className="size-4 shrink-0" aria-hidden />{name}</li>}
        {email && (
          <li>
            <a href={`mailto:${email}`} className="inline-flex min-h-11 items-center gap-2 underline-offset-4 hover:underline md:min-h-0">
              <Mail className="size-4 shrink-0" aria-hidden />{email}
            </a>
          </li>
        )}
        {phone && (
          <li>
            <a href={telHref(phone)} className="inline-flex min-h-11 items-center gap-2 underline-offset-4 hover:underline md:min-h-0">
              <Phone className="size-4 shrink-0" aria-hidden />{phone}
            </a>
          </li>
        )}
      </ul>
    </div>
  );
}
