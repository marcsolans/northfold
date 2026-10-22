"""Public contact form: store the request and notify sales (``contact_received`` email)."""

from __future__ import annotations

from messer_common.db import system_session
from messer_common.db.models import ContactRequest
from messer_common.email import ConsoleEmailAdapter, EmailError, OutgoingEmail, get_email_adapter
from messer_common.emails import render_email
from messer_common.logging import get_logger
from messer_common.settings import get_settings

log = get_logger("messer.api.contact")

TOPIC_LABELS: dict[str, dict[str, str]] = {
    "sales": {"es": "ventas", "en": "sales"},
    "enterprise": {"es": "plan Enterprise", "en": "Enterprise plan"},
    "support": {"es": "soporte", "en": "support"},
    "security": {"es": "seguridad y cumplimiento", "en": "security and compliance"},
    "partnership": {"es": "colaboraciones", "en": "partnerships"},
    "press": {"es": "prensa", "en": "press"},
    "other": {"es": "otro tema", "en": "another topic"},
}


async def create_contact_request(
    *, name: str, email: str, company: str | None, message: str, topic: str
) -> ContactRequest:
    async with system_session() as s:
        request = ContactRequest(name=name, email=email, company=company, message=message, topic=topic)
        s.add(request)
        await s.flush()
        await s.refresh(request)
    return request


async def notify_sales(request: ContactRequest, *, locale: str) -> bool:
    """Email the sales inbox (reply-to = the requester). Returns False if delivery failed; the request is kept."""
    settings = get_settings()
    # The sales team reads Spanish; the requester's language is noted in the footer.
    context = {
        "name": request.name,
        "email": request.email,
        "company": request.company or "—",
        "topic": TOPIC_LABELS.get(request.topic, TOPIC_LABELS["other"])["es"],
        "message": request.message,
        "locale": locale,
    }
    subject, html, text = render_email("contact_received", context, "es")
    outgoing = OutgoingEmail(
        to=settings.sales_email,
        subject=subject,
        html=html,
        text=text,
        reply_to=request.email,
        tags=["contact_received"],
        headers={"X-Messer-Contact-Id": str(request.id)},
    )
    try:
        await get_email_adapter().send(outgoing)
        return True
    except EmailError as exc:
        if settings.messer_env in ("local", "test"):
            await ConsoleEmailAdapter().send(outgoing)
            return True
        log.error("contact.notify_failed", contact_id=str(request.id), error=str(exc))
        return False
