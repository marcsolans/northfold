"""Email channel: one inbound address per channel (``ch-<token>@MESSER_INBOUND_EMAIL_DOMAIN``) and threaded replies.

Inbound mail arrives from the email provider's inbound webhook (Postmark's JSON format, or the normalized
``{from, to, subject, text, html, message_id, in_reply_to, references}`` used by the triggers' inbound email)
either on the channel's own URL (``/api/channels/{id}/email?token=<webhook secret>``) or on the shared
``/api/channels/inbound/email`` URL, which routes by address. Auto-replies and bounces are ignored to avoid loops.

Replies go through the platform's transactional email adapter with ``Reply-To`` set to the channel address and
``In-Reply-To``/``References`` set so mail clients keep the thread.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import re
import secrets
from email.utils import make_msgid, parseaddr
from typing import Any

from ..email import ConsoleEmailAdapter, EmailError, OutgoingEmail, get_email_adapter
from ..settings import get_settings
from .base import (
    ChannelAdapter,
    ChannelContext,
    CheckResult,
    InboundMessage,
    InboundRequest,
    InvalidSignature,
    ReplyTarget,
    SendError,
)
from .formatting import to_html, to_plain

ADDRESS_PREFIX = "ch-"
_ADDRESS = re.compile(r"ch-([0-9a-f]{16})@", re.IGNORECASE)
_LOOP_SENDERS = ("mailer-daemon", "postmaster", "no-reply", "noreply")
_QUOTE_INTRO = re.compile(
    r"^(On .+ wrote:|El .+ escribió:|-----\s*Original Message\s*-----|-----\s*Mensaje original\s*-----)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def inbound_address(config: dict[str, Any]) -> str | None:
    token = config.get("address_token")
    if not token:
        return None
    return f"{ADDRESS_PREFIX}{token}@{get_settings().messer_inbound_email_domain}"


def address_tokens(*fields: str) -> set[str]:
    """Channel address tokens found in recipient fields (To, Cc, OriginalRecipient)."""
    return {m.group(1).lower() for f in fields for m in _ADDRESS.finditer(f or "")}


def _headers(raw: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    headers = raw.get("Headers") or raw.get("headers") or []
    if isinstance(headers, dict):
        return {str(k).lower(): str(v) for k, v in headers.items()}
    for h in headers:
        if isinstance(h, dict) and h.get("Name"):
            out[str(h["Name"]).lower()] = str(h.get("Value") or "")
    return out


def normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """Postmark inbound JSON or the normalized format → one dict."""
    headers = _headers(raw)
    if "From" in raw or "TextBody" in raw:
        full = raw.get("FromFull") or {}
        return {
            "from": str(full.get("Email") or raw.get("From") or ""),
            "from_name": str(full.get("Name") or "") or None,
            "to": ", ".join(str(raw.get(k) or "") for k in ("OriginalRecipient", "To", "Cc") if raw.get(k)),
            "subject": str(raw.get("Subject") or ""),
            "text": str(raw.get("StrippedTextReply") or raw.get("TextBody") or ""),
            "html": raw.get("HtmlBody"),
            "message_id": headers.get("message-id") or (f"<{raw['MessageID']}>" if raw.get("MessageID") else None),
            "in_reply_to": headers.get("in-reply-to"),
            "references": headers.get("references", ""),
            "headers": headers,
            "stripped": bool(raw.get("StrippedTextReply")),
        }
    name, addr = parseaddr(str(raw.get("from") or raw.get("sender") or ""))
    return {
        "from": addr,
        "from_name": name or None,
        "to": str(raw.get("to") or ""),
        "subject": str(raw.get("subject") or ""),
        "text": str(raw.get("text") or ""),
        "html": raw.get("html"),
        "message_id": raw.get("message_id") or headers.get("message-id"),
        "in_reply_to": raw.get("in_reply_to") or headers.get("in-reply-to"),
        "references": str(raw.get("references") or headers.get("references") or ""),
        "headers": headers,
        "stripped": False,
    }


def _strip_quoted(text: str) -> str:
    """Drop the quoted previous message from a reply (``> …`` lines and the "On … wrote:" block)."""
    intro = _QUOTE_INTRO.search(text)
    if intro:
        text = text[: intro.start()]
    lines = [line for line in text.splitlines() if not line.lstrip().startswith(">")]
    return "\n".join(lines).strip()


def _html_to_text(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?</\1>", "", value)
    value = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", value)
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(value)).strip()


def is_auto_message(email: dict[str, Any]) -> bool:
    headers = email.get("headers") or {}
    auto = str(headers.get("auto-submitted") or "no").lower()
    precedence = str(headers.get("precedence") or "").lower()
    sender = str(email.get("from") or "").lower()
    own = parseaddr(get_settings().messer_email_from)[1].lower()
    return (
        auto != "no"
        or precedence in ("bulk", "junk", "list", "auto_reply")
        or "x-autoreply" in headers
        or "x-autorespond" in headers
        or sender.split("@")[0] in _LOOP_SENDERS
        or (bool(own) and sender == own)
    )


class EmailAdapter(ChannelAdapter):
    provider = "email"
    label = "Email"
    max_text = 100_000
    config_keys = ("address_token", "from_name", "subject_prefix")

    def provider_config(self, config: dict[str, Any]) -> dict[str, Any]:
        out = super().provider_config(config)
        out.pop("address_token", None)  # generated by the platform, never edited
        for key in ("from_name", "subject_prefix"):
            if key in out and (not isinstance(out[key], str) or len(out[key]) > 80):
                raise ValueError(f"«{key}» debe ser un texto corto (máximo 80 caracteres)")
        return out

    def initial_config(self) -> dict[str, Any]:
        return {"address_token": secrets.token_hex(8)}

    # ------------------------------------------------------------------ inbound

    async def verify(self, ctx: ChannelContext, request: InboundRequest) -> None:
        supplied = request.query.get("token") or ""
        header = request.header("authorization") or ""
        if not supplied and header.lower().startswith("basic "):
            try:
                supplied = base64.b64decode(header[6:]).decode().split(":", 1)[-1]
            except (ValueError, UnicodeDecodeError):
                supplied = ""
        elif not supplied and header.lower().startswith("bearer "):
            supplied = header[7:].strip()
        if not ctx.webhook_secret or not supplied or not hmac.compare_digest(supplied, ctx.webhook_secret):
            raise InvalidSignature("Token del webhook de email no válido")

    def parse(self, ctx: ChannelContext, request: InboundRequest) -> list[InboundMessage]:
        raw = request.json()
        if not isinstance(raw, dict):
            return []
        message = self.message_from(normalize(raw))
        return [message] if message else []

    def message_from(self, email: dict[str, Any]) -> InboundMessage | None:
        sender = str(email.get("from") or "").strip().lower()
        if not sender or "@" not in sender or is_auto_message(email):
            return None
        body = str(email.get("text") or "")
        if not body and email.get("html"):
            body = _html_to_text(str(email["html"]))
        if not email.get("stripped"):
            body = _strip_quoted(body)
        subject = str(email.get("subject") or "").strip()
        is_reply = bool(email.get("in_reply_to")) or subject.lower().startswith(("re:", "aw:", "rv:"))
        text = body if is_reply or not subject else f"Asunto: {subject}\n\n{body}".strip()
        if not text.strip():
            return None
        message_id = str(email.get("message_id") or "").strip() or None
        references = [
            r for r in re.split(r"\s+", f"{email.get('references') or ''} {email.get('in_reply_to') or ''}") if r
        ]
        external = message_id or "sha:" + hashlib.sha256(f"{sender}|{subject}|{body}".encode()).hexdigest()[:40]
        return InboundMessage(
            external_id=external[:255],
            conversation_key=sender[:255],
            sender_id=sender[:255],
            sender_name=email.get("from_name"),
            text=text[:100_000],
            reply={
                "to": sender,
                "subject": subject[:300],
                "message_id": message_id,
                "references": list(dict.fromkeys(references))[-10:],
            },
        )

    # ------------------------------------------------------------------ outbound

    async def send_text(self, ctx: ChannelContext, target: ReplyTarget, text: str) -> list[str]:
        recipient = parseaddr(str(target.reply.get("to") or target.conversation_key))[1]
        if "@" not in recipient:
            raise SendError("No hay una dirección de email a la que responder", code="missing_target")
        subject = str(target.reply.get("subject") or "").strip()
        prefix = str(ctx.config.get("subject_prefix") or "").strip()
        if not subject:
            subject = f"{prefix} Respuesta".strip() if prefix else "Respuesta"
        elif not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        domain = get_settings().messer_inbound_email_domain
        message_id = make_msgid(domain=domain)
        headers = {"Message-ID": message_id, "Auto-Submitted": "auto-replied"}
        original = target.reply.get("message_id")
        if original:
            refs = [*list(target.reply.get("references") or []), original]
            headers["In-Reply-To"] = str(original)
            headers["References"] = " ".join(dict.fromkeys(str(r) for r in refs))
        email = OutgoingEmail(
            to=recipient,
            subject=subject[:300],
            html=to_html(text),
            text=to_plain(text),
            reply_to=inbound_address(ctx.config),
            tags=["channel"],
            headers=headers,
        )
        adapter = get_email_adapter()
        try:
            await adapter.send(email)
        except EmailError as exc:
            if get_settings().messer_env in ("local", "test"):
                await ConsoleEmailAdapter().send(email)
            else:
                raise SendError(f"No se pudo enviar el email: {exc}", code="email_failed", retryable=True) from exc
        return [message_id]

    async def check(self, ctx: ChannelContext) -> CheckResult:
        settings = get_settings()
        return CheckResult(
            details={
                "address": inbound_address(ctx.config),
                "email_provider": settings.messer_email_provider,
                "shared_inbound_configured": bool(settings.messer_inbound_email_secret),
            }
        )
