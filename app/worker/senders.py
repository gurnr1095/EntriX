"""Ways to hand a finished email to a provider (besides plain SMTP, in outbox_worker.py)."""

import base64
import logging
from email.message import EmailMessage
from email.utils import parseaddr

import httpx

from app.config import get_settings, sender_address

log = logging.getLogger("outbox_worker")

BREVO_URL = "https://api.brevo.com/v3/smtp/email"
DEFAULT_QUOTA_DELAY = 60 * 60  # when the provider says "too many" without saying for how long
CONFIG_ERROR_DELAY = 15 * 60  # bad API key: retry now and then, loudly, while it is fixed


class DeferredError(Exception):
    """Sending cannot work *right now*, through no fault of this email.

    The worker postpones the row without counting an attempt. That matters: a provider's daily
    quota or a wrong API key would otherwise use up every row's attempts within minutes and
    mark a whole launch's emails `failed`, when all they need is time or a fixed setting.
    """

    def __init__(self, delay_seconds: int, reason: str) -> None:
        super().__init__(reason)
        self.delay_seconds = delay_seconds
        self.reason = reason


class BrevoSender:
    """Send through Brevo's HTTPS API (port 443), for hosts that block SMTP ports.

    Brevo's transactional API has no inline (cid:) images, so the QR code travels as a normal
    attachment; `inline_images = False` tells the message builder to lay the email out that way.
    """

    inline_images = False

    def __init__(
        self,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        url: str = BREVO_URL,
    ) -> None:
        self._api_key = api_key if api_key is not None else get_settings().brevo_api_key
        self._client = client or httpx.Client()
        self._url = url

    @staticmethod
    def payload(msg: EmailMessage) -> dict[str, object]:
        sender_name, _ = parseaddr(msg["From"])
        sender_email = sender_address(str(msg["From"]))
        if sender_email is None:
            raise DeferredError(
                CONFIG_ERROR_DELAY,
                f"MAIL_FROM has no usable email address ({msg['From']!r}): fix it and redeploy",
            )
        _, to_email = parseaddr(msg["To"])
        text_part = msg.get_body(preferencelist=("plain",))
        html_part = msg.get_body(preferencelist=("html",))
        body: dict[str, object] = {
            "sender": {"email": sender_email, **({"name": sender_name} if sender_name else {})},
            "to": [{"email": to_email}],
            "subject": str(msg["Subject"]),
            "textContent": text_part.get_content() if text_part else "",
            "htmlContent": html_part.get_content() if html_part else "",
            "headers": {"X-Entrix-Outbox-Id": str(msg["X-Entrix-Outbox-Id"])},
        }
        attachments = [
            {
                "name": part.get_filename() or "attachment",
                "content": base64.b64encode(part.get_payload(decode=True)).decode(),
            }
            for part in msg.iter_attachments()
        ]
        if attachments:
            body["attachment"] = attachments
        return body

    def __call__(self, msg: EmailMessage) -> None:
        response = self._client.post(
            self._url,
            json=self.payload(msg),
            headers={"api-key": self._api_key, "accept": "application/json"},
            timeout=15,
        )
        status = response.status_code
        if status in (200, 201, 202):
            return
        if status == 429:
            delay = _retry_after(response) or DEFAULT_QUOTA_DELAY
            raise DeferredError(delay, "Brevo is rate limiting us or the daily quota is used up")
        if status in (401, 403):
            log.error("Brevo rejected the API key or the request (%s): check BREVO_API_KEY", status)
            raise DeferredError(
                CONFIG_ERROR_DELAY,
                f"Brevo refused our credentials ({status}): {response.text[:200]}",
            )
        if status == 400 and "sender" in response.text.lower():
            # Every email would fail the same way, so this is configuration, not one bad email:
            # wait for a fix instead of using up each row's attempts.
            log.error("Brevo says the sender is invalid, check MAIL_FROM: %s", response.text[:200])
            raise DeferredError(
                CONFIG_ERROR_DELAY,
                f"Brevo says the sender is not valid ({response.text[:200]}): check that "
                "MAIL_FROM is an address verified in Brevo, without quotes",
            )
        raise RuntimeError(f"Brevo returned {status}: {response.text[:300]}")


def _retry_after(response: httpx.Response) -> int | None:
    try:
        seconds = int(response.headers.get("retry-after", ""))
    except ValueError:
        return None
    return min(max(seconds, 60), 6 * 60 * 60)
