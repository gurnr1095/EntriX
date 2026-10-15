"""Send a real test confirmation email, to find out whether it reaches the inbox.

    python -m scripts.send_test_email you@gmail.com friend@outlook.com ...

Uses the same settings as the app (EMAIL_BACKEND, BREVO_API_KEY or SMTP_*, MAIL_FROM), read
from the environment or a `.env` file. It touches no database. The QR code in the email is
well-formed but belongs to no registration.

Why it exists: with Brevo and no domain of your own, Brevo cannot authenticate your sender
address, so whether mail lands in the inbox or in spam depends on the receiving provider.
Send one to each kind of address your students use, then look in the inbox AND the spam
folder, and write down what you find before relying on email for an event.
"""

import sys
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from app.config import Settings, get_settings, validate_worker_startup
from app.models import RegistrationStatus
from app.services import qr
from app.worker.emails import MailContext, build_message
from app.worker.outbox_worker import get_sender
from app.worker.senders import DeferredError

Sender = Callable[[EmailMessage], None]


def send_test_emails(
    recipients: Sequence[str], sender: Sender, settings: Settings
) -> list[tuple[str, str | None]]:
    """Send one test email to each recipient. Returns (recipient, error or None) pairs."""
    inline = getattr(sender, "inline_images", True)
    results: list[tuple[str, str | None]] = []
    for number, recipient in enumerate(recipients, start=1):
        ctx = MailContext(
            registration_id=str(uuid.uuid4()),
            status=RegistrationStatus.confirmed,
            to_email=recipient,
            name=recipient.split("@", 1)[0],
            category_name="Table Tennis Singles",
            event_name="EntriX test event",
            venue="Main Ground",
            starts_at=datetime.now(UTC) + timedelta(days=7),
            token=qr.sign(uuid.uuid4(), uuid.uuid4()),
        )
        message = build_message(
            "registration_confirmed", ctx, number, settings.mail_from, inline_qr=inline
        )
        assert message is not None
        message.replace_header("Subject", f"[EntriX test] {message['Subject']}")
        try:
            sender(message)
            results.append((recipient, None))
        except DeferredError as exc:
            results.append((recipient, f"provider said not now: {exc.reason}"))
        except Exception as exc:  # noqa: BLE001 - report every failure, do not stop at the first
            results.append((recipient, f"{type(exc).__name__}: {exc}"))
    return results


# The example addresses used in the docs. Sending to them would email strangers who really
# own those mailboxes (and bounces count against your sender reputation).
PLACEHOLDER_ADDRESSES = {
    "you@gmail.com",
    "you@example.com",
    "you@college.edu",
    "friend@outlook.com",
    "another@outlook.com",
}
LOCAL_SMTP_HOSTS = {"localhost", "127.0.0.1", "mailhog"}


def main(argv: Sequence[str]) -> int:
    allow_local = "--allow-local" in argv
    recipients = [a for a in argv if "@" in a]
    if not recipients:
        print(__doc__)
        return 2
    placeholders = [r for r in recipients if r.lower() in PLACEHOLDER_ADDRESSES]
    if placeholders:
        print(
            f"Not sending: {', '.join(placeholders)} are example addresses from the docs.\n"
            "Use mailboxes you own (for example your own Gmail, an Outlook one and your "
            "college one)."
        )
        return 2

    settings = get_settings()
    validate_worker_startup(settings)
    print(f"backend={settings.email_backend} from={settings.mail_from}")
    local = settings.email_backend == "smtp" and settings.smtp_host in LOCAL_SMTP_HOSTS
    if local and not allow_local:
        print(
            f"\nNot sending: EMAIL_BACKEND is 'smtp' and points at {settings.smtp_host}:"
            f"{settings.smtp_port}, a local test inbox (MailHog at http://localhost:8025), so\n"
            "nothing would reach a real mailbox. To test Brevo, give it these three settings,\n"
            "either for this terminal only (PowerShell; nothing is saved to disk):\n\n"
            '    $env:EMAIL_BACKEND = "brevo"\n'
            '    $env:BREVO_API_KEY = "<your Brevo API key>"\n'
            '    $env:MAIL_FROM = "<the sender address you verified in Brevo>"\n\n'
            "or in a git-ignored .env file (copy .env.example and fill in EMAIL_BACKEND=brevo,\n"
            "BREVO_API_KEY and MAIL_FROM). With a Brevo key in .env, a worker you run locally\n"
            "will send REAL emails through Brevo, so remove those lines when you are done.\n\n"
            "Then run this again. (Use --allow-local to send to MailHog anyway.)"
        )
        return 3

    failures = 0
    for recipient, error in send_test_emails(recipients, get_sender(), settings):
        if error:
            failures += 1
            print(f"  FAILED  {recipient}: {error}")
        else:
            print(f"  sent    {recipient}")
    if not failures:
        if local:
            print("\nThese went to MailHog only: open http://localhost:8025 to see them.")
        else:
            print(
                "\nNow check each inbox AND its spam folder, and note where the email landed.\n"
                "Look at the 'From' line too: with Brevo and no domain of your own it may show a\n"
                "Brevo address instead of yours, which is expected."
            )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
