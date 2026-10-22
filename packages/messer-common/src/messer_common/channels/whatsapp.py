"""WhatsApp Business (Meta Cloud API).

* Webhook verification: ``GET ?hub.mode=subscribe&hub.verify_token=…&hub.challenge=…`` answered with the
  challenge when the token is the channel's webhook secret (or ``WHATSAPP_VERIFY_TOKEN`` for platform numbers).
* Events: ``POST`` signed with ``X-Hub-Signature-256: sha256=<hex hmac-sha256(app secret, raw body)>``.
  ``messages`` become inbound messages (text; media, locations and contacts as placeholders); ``statuses``
  (sent/delivered/read receipts) are ignored.
* Replies: ``POST /{version}/{phone_number_id}/messages``. Free-form messages are only allowed within 24 hours of
  the user's last message; after that WhatsApp requires an approved template (``config.template``), and without
  one the delivery fails with ``whatsapp_window_closed``.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from . import http
from .base import (
    ChannelAdapter,
    ChannelContext,
    CheckResult,
    CredentialField,
    InboundMessage,
    InboundRequest,
    InvalidConfig,
    InvalidSignature,
    ReplyTarget,
    SendError,
    WebhookReply,
)
from .formatting import single_line, to_whatsapp

GRAPH_URL = "https://graph.facebook.com"
DEFAULT_API_VERSION = "v21.0"
SERVICE_WINDOW = timedelta(hours=24)
TEMPLATE_PARAM_MAX = 1000
# Meta error codes: re-engagement required (outside the 24 h window), rate limits, expired/invalid token.
REENGAGEMENT_CODES = {131047}
RATE_LIMIT_CODES = {4, 80007, 130429, 131048, 131056}
AUTH_CODES = {190, 10, 200}

_MEDIA_LABELS = {
    "image": "Imagen",
    "video": "Vídeo",
    "audio": "Audio",
    "document": "Documento",
    "sticker": "Sticker",
}
_TEMPLATE_NAME = re.compile(r"^[a-z0-9_]{1,512}$")
_LANGUAGE = re.compile(r"^[a-z]{2,3}(_[A-Z]{2})?$")


def _message_content(m: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]]]:
    """(text, kind, attachments) of one WhatsApp message."""
    kind = str(m.get("type") or "")
    if kind == "text":
        return str((m.get("text") or {}).get("body") or ""), "text", []
    if kind in _MEDIA_LABELS:
        media = m.get(kind) or {}
        caption = str(media.get("caption") or "").strip()
        name = media.get("filename")
        label = f"[{_MEDIA_LABELS[kind]}{': ' + str(name) if name else ''}]"
        attachment = {"type": kind, "id": media.get("id"), "mime_type": media.get("mime_type"), "filename": name}
        return (f"{label} {caption}".strip(), "media", [attachment])
    if kind == "location":
        loc = m.get("location") or {}
        where = " · ".join(str(loc[k]) for k in ("name", "address") if loc.get(k))
        coords = f"({loc.get('latitude')}, {loc.get('longitude')})"
        return f"[Ubicación] {where} {coords}".strip(), "location", []
    if kind == "contacts":
        names = []
        for c in m.get("contacts") or []:
            name = (c.get("name") or {}).get("formatted_name") or ""
            phones = ", ".join(str(p.get("phone")) for p in c.get("phones") or [] if p.get("phone"))
            names.append(f"{name} {phones}".strip())
        return "[Contacto] " + "; ".join(names), "contacts", []
    if kind == "interactive":
        inter = m.get("interactive") or {}
        reply = inter.get("button_reply") or inter.get("list_reply") or {}
        text = str(reply.get("title") or "")
        if reply.get("description"):
            text = f"{text} — {reply['description']}"
        return text, "interactive", []
    if kind == "button":
        return str((m.get("button") or {}).get("text") or ""), "interactive", []
    if kind == "reaction":
        return "", "reaction", []
    return f"[Mensaje no compatible: {kind or 'desconocido'}]", "unsupported", []


def _meta_error(res_json: Any) -> tuple[int | None, str]:
    if isinstance(res_json, dict) and isinstance(res_json.get("error"), dict):
        err = res_json["error"]
        code = err.get("code")
        return (int(code) if isinstance(code, int | str) and str(code).isdigit() else None), str(
            err.get("message") or ""
        )
    return None, ""


class WhatsAppAdapter(ChannelAdapter):
    provider = "whatsapp"
    label = "WhatsApp"
    max_text = 4096
    credential_fields = (
        CredentialField("access_token", platform="whatsapp_access_token"),
        CredentialField("app_secret", platform="whatsapp_app_secret"),
    )
    config_keys = ("phone_number_id", "business_account_id", "api_version", "template", "display_phone_number")
    platform_config = {"phone_number_id": "whatsapp_phone_number_id"}
    required_config = ("phone_number_id",)

    def provider_config(self, config: dict[str, Any]) -> dict[str, Any]:
        out = super().provider_config(config)
        for key in ("phone_number_id", "business_account_id"):
            if key in out:
                value = str(out[key]).strip()
                if not value.isdigit():
                    raise ValueError(f"«{key}» debe ser el identificador numérico que muestra Meta")
                out[key] = value
        if "api_version" in out and not re.fullmatch(r"v\d{1,2}\.\d", str(out["api_version"])):
            raise ValueError("La versión de la API debe tener el formato v21.0")
        template = out.get("template")
        if template is not None:
            if not isinstance(template, dict) or not _TEMPLATE_NAME.match(str(template.get("name") or "")):
                raise ValueError("La plantilla necesita un nombre en minúsculas, números y guiones bajos")
            language = str(template.get("language") or "es")
            if not _LANGUAGE.match(language):
                raise ValueError("El idioma de la plantilla debe ser un código como es o es_ES")
            out["template"] = {
                "name": template["name"],
                "language": language,
                "body_parameter": bool(template.get("body_parameter", True)),
            }
        return out

    def _graph(self, ctx: ChannelContext, path: str) -> str:
        version = ctx.config.get("api_version") or DEFAULT_API_VERSION
        return f"{GRAPH_URL}/{version}/{path.lstrip('/')}"

    def _auth(self, ctx: ChannelContext) -> dict[str, str]:
        token = ctx.credentials.get("access_token")
        if not token:
            raise SendError("Falta el token de acceso de WhatsApp", code="missing_credentials", auth=True)
        return {"Authorization": f"Bearer {token}"}

    # ------------------------------------------------------------------ inbound

    def handshake(self, ctx: ChannelContext, request: InboundRequest) -> WebhookReply | None:
        if request.method != "GET":
            return None
        mode = request.query.get("hub.mode")
        token = request.query.get("hub.verify_token") or ""
        challenge = request.query.get("hub.challenge") or ""
        accepted = [t for t in (ctx.webhook_secret, ctx.config.get("platform_verify_token")) if t]
        if mode == "subscribe" and token and any(hmac.compare_digest(token, t) for t in accepted):
            return WebhookReply(200, challenge, media_type="text/plain")
        return WebhookReply(403, "invalid verify token", media_type="text/plain")

    async def verify(self, ctx: ChannelContext, request: InboundRequest) -> None:
        secret = ctx.credentials.get("app_secret")
        if not secret:
            raise InvalidSignature("El canal no tiene el App Secret de Meta configurado")
        header = request.header("x-hub-signature-256") or ""
        if not header.startswith("sha256="):
            raise InvalidSignature("Falta la firma X-Hub-Signature-256")
        expected = hmac.new(str(secret).encode(), request.body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, header[7:].strip().lower()):
            raise InvalidSignature("Firma de WhatsApp no válida")

    def parse(self, ctx: ChannelContext, request: InboundRequest) -> list[InboundMessage]:
        data = request.json()
        if not isinstance(data, dict) or data.get("object") != "whatsapp_business_account":
            return []
        own_number = str(ctx.config.get("phone_number_id") or "")
        out: list[InboundMessage] = []
        for entry in data.get("entry") or []:
            for change in (entry or {}).get("changes") or []:
                if change.get("field") != "messages":
                    continue
                value = change.get("value") or {}
                number = str((value.get("metadata") or {}).get("phone_number_id") or "")
                if own_number and number and number != own_number:
                    continue  # event for another number of the same Meta app
                names = {str(c.get("wa_id")): (c.get("profile") or {}).get("name") for c in value.get("contacts") or []}
                for m in value.get("messages") or []:
                    sender = str(m.get("from") or "")
                    if not sender or not m.get("id"):
                        continue
                    text, kind, attachments = _message_content(m)
                    if not text and not attachments:
                        continue
                    sent_at = None
                    if str(m.get("timestamp") or "").isdigit():
                        sent_at = datetime.fromtimestamp(int(m["timestamp"]), UTC)
                    out.append(
                        InboundMessage(
                            external_id=str(m["id"]),
                            conversation_key=sender,
                            sender_id=sender,
                            sender_name=names.get(sender),
                            text=text,
                            kind=kind,
                            attachments=attachments,
                            reply={"to": sender, "message_id": str(m["id"]), "phone_number_id": number or own_number},
                            sent_at=sent_at,
                        )
                    )
        return out

    # ------------------------------------------------------------------ outbound

    def format_text(self, markdown: str) -> str:
        return to_whatsapp(markdown)

    async def send_text(self, ctx: ChannelContext, target: ReplyTarget, text: str) -> list[str]:
        number = str(ctx.config.get("phone_number_id") or target.reply.get("phone_number_id") or "")
        if not number:
            raise SendError("Falta el Phone Number ID de WhatsApp", code="missing_config", auth=True)
        to = str(target.reply.get("to") or target.conversation_key)
        last = target.last_inbound_at
        if last is not None and datetime.now(UTC) - last > SERVICE_WINDOW:
            return [await self._send_template(ctx, number, to, text)]
        ids: list[str] = []
        for part in self.parts(text):
            body = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {"preview_url": False, "body": part},
            }
            res = await http.request(
                "POST", self._graph(ctx, f"{number}/messages"), provider="WhatsApp", json=body, headers=self._auth(ctx)
            )
            payload = _json(res)
            code, message = _meta_error(payload)
            if code in REENGAGEMENT_CODES:
                remaining = text if not ids else "\n\n".join(self.parts(text)[len(ids) :])
                ids.append(await self._send_template(ctx, number, to, remaining))
                return ids
            self._raise(res, code, message)
            ids.append(str(((payload or {}).get("messages") or [{}])[0].get("id") or ""))
        return [i for i in ids if i]

    async def _send_template(self, ctx: ChannelContext, number: str, to: str, text: str) -> str:
        template = ctx.config.get("template")
        if not isinstance(template, dict) or not template.get("name"):
            raise SendError(
                "Han pasado más de 24 horas desde el último mensaje del usuario y WhatsApp solo permite "
                "plantillas aprobadas. Configura una plantilla en el canal para poder responder.",
                code="whatsapp_window_closed",
            )
        components: list[dict[str, Any]] = []
        if template.get("body_parameter", True):
            components.append(
                {"type": "body", "parameters": [{"type": "text", "text": single_line(text, TEMPLATE_PARAM_MAX)}]}
            )
        body = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template["name"],
                "language": {"code": template.get("language") or "es"},
                "components": components,
            },
        }
        res = await http.request(
            "POST", self._graph(ctx, f"{number}/messages"), provider="WhatsApp", json=body, headers=self._auth(ctx)
        )
        payload = _json(res)
        code, message = _meta_error(payload)
        self._raise(res, code, message, template=True)
        return str(((payload or {}).get("messages") or [{}])[0].get("id") or "")

    def _raise(self, res: Any, code: int | None, message: str, *, template: bool = False) -> None:
        if res.status_code < 400 and code is None:
            return
        if code in AUTH_CODES:
            raise SendError(f"WhatsApp rechazó el token de acceso: {message}", code="auth_failed", auth=True)
        if code in RATE_LIMIT_CODES:
            raise SendError(f"WhatsApp limita el envío: {message}", code="rate_limited", retryable=True)
        if template and res.status_code < 500:
            raise SendError(f"WhatsApp rechazó la plantilla: {message}", code="template_rejected")
        http.raise_for_send(res, "WhatsApp", message or None)

    async def check(self, ctx: ChannelContext) -> CheckResult:
        number = str(ctx.config.get("phone_number_id") or "")
        if not number:
            raise InvalidConfig("Falta el Phone Number ID de WhatsApp")
        res = await http.request(
            "GET",
            self._graph(ctx, number),
            provider="WhatsApp",
            params={"fields": "display_phone_number,verified_name,quality_rating"},
            headers=self._auth(ctx),
        )
        payload = _json(res)
        code, message = _meta_error(payload)
        self._raise(res, code, message)
        info = payload if isinstance(payload, dict) else {}
        details = {k: info.get(k) for k in ("display_phone_number", "verified_name", "quality_rating") if info.get(k)}
        updates = {"display_phone_number": info["display_phone_number"]} if info.get("display_phone_number") else {}
        return CheckResult(details=details, config_updates=updates)


def _json(res: Any) -> Any:
    try:
        return res.json()
    except ValueError:
        return None
