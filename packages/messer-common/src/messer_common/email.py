"""Transactional email adapter: console, SMTP (Mailpit locally), Postmark (EU) or Resend (EU)."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

import aiosmtplib
import httpx

from .emails import render_email
from .logging import get_logger
from .settings import get_settings

log = get_logger("messer.email")


@dataclass(slots=True)
class OutgoingEmail:
    to: str
    subject: str
    html: str
    text: str
    reply_to: str | None = None
    tags: list[str] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)


class EmailError(Exception):
    pass


class EmailAdapter(abc.ABC):
    name: str = "base"

    @abc.abstractmethod
    async def send(self, email: OutgoingEmail) -> str | None: ...


class ConsoleEmailAdapter(EmailAdapter):
    name = "console"
    sent: list[OutgoingEmail] = []

    async def send(self, email: OutgoingEmail) -> str | None:
        ConsoleEmailAdapter.sent.append(email)
        log.info("email.console", to=email.to, subject=email.subject, text=email.text[:2000])
        return None


class SmtpEmailAdapter(EmailAdapter):
    name = "smtp"

    async def send(self, email: OutgoingEmail) -> str | None:
        s = get_settings()
        msg = EmailMessage()
        name, addr = parseaddr(s.messer_email_from)
        msg["From"] = formataddr((name, addr))
        msg["To"] = email.to
        msg["Subject"] = email.subject
        if email.reply_to:
            msg["Reply-To"] = email.reply_to
        for k, v in email.headers.items():
            msg[k] = v
        msg.set_content(email.text)
        msg.add_alternative(email.html, subtype="html")
        try:
            await aiosmtplib.send(
                msg,
                hostname=s.smtp_host,
                port=s.smtp_port,
                username=s.smtp_user or None,
                password=s.smtp_password or None,
                start_tls=s.smtp_tls,
                timeout=15,
            )
        except (aiosmtplib.SMTPException, OSError) as exc:
            raise EmailError(f"SMTP send failed: {exc}") from exc
        return msg.get("Message-ID")


class PostmarkEmailAdapter(EmailAdapter):
    name = "postmark"

    async def send(self, email: OutgoingEmail) -> str | None:
        s = get_settings()
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.post(
                "https://api.postmarkapp.com/email",
                headers={"X-Postmark-Server-Token": s.postmark_server_token, "Accept": "application/json"},
                json={
                    "From": s.messer_email_from,
                    "To": email.to,
                    "Subject": email.subject,
                    "HtmlBody": email.html,
                    "TextBody": email.text,
                    "ReplyTo": email.reply_to,
                    "MessageStream": "outbound",
                    "Headers": [{"Name": k, "Value": v} for k, v in email.headers.items()],
                },
            )
        if res.status_code >= 300:
            raise EmailError(f"Postmark send failed: {res.status_code} {res.text}")
        return res.json().get("MessageID")


class ResendEmailAdapter(EmailAdapter):
    name = "resend"

    async def send(self, email: OutgoingEmail) -> str | None:
        s = get_settings()
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {s.resend_api_key}"},
                json={
                    "from": s.messer_email_from,
                    "to": [email.to],
                    "subject": email.subject,
                    "html": email.html,
                    "text": email.text,
                    "reply_to": email.reply_to,
                    "headers": email.headers,
                },
            )
        if res.status_code >= 300:
            raise EmailError(f"Resend send failed: {res.status_code} {res.text}")
        return res.json().get("id")


_adapter: EmailAdapter | None = None


def get_email_adapter() -> EmailAdapter:
    global _adapter
    if _adapter is None:
        s = get_settings()
        provider = s.messer_email_provider
        if provider == "postmark" and s.postmark_server_token:
            _adapter = PostmarkEmailAdapter()
        elif provider == "resend" and s.resend_api_key:
            _adapter = ResendEmailAdapter()
        elif provider == "smtp":
            _adapter = SmtpEmailAdapter()
        else:
            _adapter = ConsoleEmailAdapter()
    return _adapter


def set_email_adapter(adapter: EmailAdapter | None) -> None:
    global _adapter
    _adapter = adapter


async def send_template(to: str, template: str, context: dict[str, object], locale: str = "es") -> str | None:
    """Render a template and send it. Falls back to the console adapter if SMTP is unreachable locally."""
    subject, html, text = render_email(template, context, locale)
    email = OutgoingEmail(to=to, subject=subject, html=html, text=text, tags=[template])
    adapter = get_email_adapter()
    try:
        return await adapter.send(email)
    except EmailError:
        if get_settings().messer_env in ("local", "test"):
            log.warning("email.fallback_console", template=template, to=to)
            return await ConsoleEmailAdapter().send(email)
        raise
