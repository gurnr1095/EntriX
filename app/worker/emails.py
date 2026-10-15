import io
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from html import escape

import segno

from app.models import RegistrationStatus

IST = timezone(timedelta(hours=5, minutes=30))
_QR_TYPES = {"registration_confirmed", "waitlist_promoted"}
_KNOWN_TYPES = _QR_TYPES | {"registration_waitlisted", "registration_cancelled"}


@dataclass(frozen=True)
class MailContext:
    registration_id: str
    status: RegistrationStatus
    to_email: str
    name: str
    category_name: str
    event_name: str
    venue: str | None
    starts_at: datetime
    token: str


def _qr_png(token: str) -> bytes:
    buf = io.BytesIO()
    segno.make(token, error="m").save(buf, kind="png", scale=8, border=4)
    return buf.getvalue()


def _when(ctx: MailContext) -> str:
    return ctx.starts_at.astimezone(IST).strftime("%d %b %Y, %I:%M %p IST")


def build_message(
    event_type: str,
    ctx: MailContext,
    outbox_id: int,
    mail_from: str,
    *,
    inline_qr: bool = True,
) -> EmailMessage | None:
    """Build the email for an outbox row, or None when it should not be sent.

    `inline_qr=False` is for providers whose API cannot embed images (cid:): the QR code is
    then a normal attachment and the text says so.

    Delivery is at-least-once, so every message names the registration ID and carries
    the outbox row id: a duplicate is recognisable and harmless.
    """
    if event_type not in _KNOWN_TYPES:
        raise ValueError(f"Unknown outbox event type: {event_type}")
    # A seat that was cancelled before we got to it must not receive a QR.
    if event_type in _QR_TYPES and ctx.status not in (
        RegistrationStatus.confirmed,
        RegistrationStatus.checked_in,
    ):
        return None

    place = f" at {ctx.venue}" if ctx.venue else ""
    ref = f"Registration ID: {ctx.registration_id}"
    subject, lines = {
        "registration_confirmed": (
            f"You're in: {ctx.category_name} ({ctx.event_name})",
            [f"Your seat in {ctx.category_name} is confirmed."],
        ),
        "waitlist_promoted": (
            f"A seat opened up: {ctx.category_name} ({ctx.event_name})",
            [
                "Good news: you moved off the waitlist.",
                f"Your seat in {ctx.category_name} is confirmed.",
            ],
        ),
        "registration_waitlisted": (
            f"You're on the waitlist: {ctx.category_name} ({ctx.event_name})",
            [
                f"{ctx.category_name} is full, so you are on the waitlist.",
                "We will email you if a seat opens up.",
            ],
        ),
        "registration_cancelled": (
            f"Registration cancelled: {ctx.category_name} ({ctx.event_name})",
            [f"Your registration for {ctx.category_name} has been cancelled."],
        ),
    }[event_type]
    details = f"{ctx.event_name}{place}, {_when(ctx)}"

    text_lines = [f"Hi {ctx.name},", "", *lines, details, ref]
    html_lines = [f"<p>Hi {escape(ctx.name)},</p>", *(f"<p>{escape(x)}</p>" for x in lines)]
    html_lines.append(f"<p>{escape(details)}<br><small>{escape(ref)}</small></p>")

    if event_type in _QR_TYPES and inline_qr:
        text_lines += ["", "Show this check-in code at the venue:", ctx.token]
        html_lines.append(
            "<p>Show this QR code at the venue:</p>"
            '<p><img src="cid:qr" alt="Check-in QR code" width="240" height="240"></p>'
            "<p><small>If the image does not load, your code is:<br>"
            f"{escape(ctx.token)}</small></p>"
        )
    elif event_type in _QR_TYPES:
        text_lines += [
            "",
            "Your check-in QR code is attached to this email (qr.png). Show it at the venue.",
            "If you cannot open the attachment, your code is:",
            ctx.token,
        ]
        html_lines.append(
            "<p>Your check-in QR code is attached to this email (<b>qr.png</b>). "
            "Show it at the venue.</p>"
            "<p><small>If you cannot open the attachment, your code is:<br>"
            f"{escape(ctx.token)}</small></p>"
        )
    alternatives = EmailMessage()
    alternatives.set_content("\n".join(text_lines))
    alternatives.add_alternative(
        "<html><body>" + "".join(html_lines) + "</body></html>", subtype="html"
    )

    msg = alternatives
    if event_type in _QR_TYPES and not inline_qr:
        # multipart/mixed[ alternative[text, html], qr.png ]: an ordinary attachment.
        alternatives.add_attachment(
            _qr_png(ctx.token), maintype="image", subtype="png", filename="qr.png"
        )
    elif event_type in _QR_TYPES:
        # multipart/related[ alternative[text, html], image ]: the image sits beside the
        # alternatives, the layout mail clients (and MailHog's cid lookup) expect.
        image = EmailMessage()
        image.set_content(
            _qr_png(ctx.token),
            maintype="image",
            subtype="png",
            disposition="inline",
            filename="qr.png",
            cid="<qr>",
        )
        msg = EmailMessage()
        msg["Content-Type"] = "multipart/related"
        msg.set_payload([alternatives, image])

    msg["From"] = mail_from
    msg["To"] = ctx.to_email
    msg["Subject"] = subject
    msg["X-Entrix-Outbox-Id"] = str(outbox_id)
    return msg
