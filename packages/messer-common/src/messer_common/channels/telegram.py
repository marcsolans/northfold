"""Telegram (Bot API).

* Connecting a live channel calls ``setWebhook`` with the channel's webhook URL and a ``secret_token`` (the
  channel's webhook secret); Telegram sends it back in ``X-Telegram-Bot-Api-Secret-Token`` on every update.
  Disconnecting calls ``deleteWebhook``.
* ``message`` updates become inbound messages (captions and media as placeholders). In groups the bot only
  answers when it is mentioned or replied to, unless ``config.group_mode = "all"``.
* Replies: ``sendMessage`` as plain text (no parse mode, so no entity errors), split at 4,096 characters.
"""

from __future__ import annotations

import hmac
import re
from datetime import UTC, datetime
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
)
from .formatting import to_plain

API_URL = "https://api.telegram.org"
ALLOWED_UPDATES = ["message"]

_MEDIA = {
    "photo": "Foto",
    "video": "Vídeo",
    "voice": "Nota de voz",
    "audio": "Audio",
    "video_note": "Vídeo",
    "animation": "GIF",
}


def _content(msg: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]]]:
    text = str(msg.get("text") or msg.get("caption") or "")
    attachments: list[dict[str, Any]] = []
    labels: list[str] = []
    for key, label in _MEDIA.items():
        if msg.get(key):
            labels.append(f"[{label}]")
            attachments.append({"type": key})
    if msg.get("document"):
        doc = msg["document"]
        labels.append(f"[Documento: {doc.get('file_name') or 'archivo'}]")
        attachments.append({"type": "document", "name": doc.get("file_name"), "mime_type": doc.get("mime_type")})
    if msg.get("sticker"):
        labels.append(f"[Sticker {msg['sticker'].get('emoji') or ''}]".replace(" ]", "]"))
    if msg.get("location"):
        loc = msg["location"]
        labels.append(f"[Ubicación] ({loc.get('latitude')}, {loc.get('longitude')})")
    if msg.get("contact"):
        c = msg["contact"]
        name = " ".join(str(c.get(k)) for k in ("first_name", "last_name") if c.get(k))
        labels.append(f"[Contacto] {name} {c.get('phone_number') or ''}".strip())
    full = " ".join([*labels, text]).strip()
    kind = "media" if attachments else ("location" if msg.get("location") else "text")
    return full, kind, attachments


class TelegramAdapter(ChannelAdapter):
    provider = "telegram"
    label = "Telegram"
    max_text = 4096
    credential_fields = (CredentialField("bot_token", platform="telegram_bot_token"),)
    config_keys = ("bot_username", "bot_id", "group_mode")

    def provider_config(self, config: dict[str, Any]) -> dict[str, Any]:
        out = super().provider_config(config)
        if "group_mode" in out and out["group_mode"] not in ("mention", "all"):
            raise ValueError("«group_mode» debe ser «mention» o «all»")
        return out

    def _url(self, ctx: ChannelContext, method: str) -> str:
        token = ctx.credentials.get("bot_token")
        if not token:
            raise SendError("Falta el token del bot de Telegram", code="missing_credentials", auth=True)
        return f"{API_URL}/bot{token}/{method}"

    async def _call(self, ctx: ChannelContext, method: str, body: dict[str, Any]) -> Any:
        res = await http.request("POST", self._url(ctx, method), provider="Telegram", json=body)
        try:
            data = res.json()
        except ValueError:
            data = {}
        if res.status_code < 400 and data.get("ok"):
            return data.get("result")
        code = int(data.get("error_code") or res.status_code)
        description = str(data.get("description") or res.reason_phrase)
        if code == 401 or code == 404:
            raise SendError(f"Telegram rechazó el token del bot: {description}", code="auth_failed", auth=True)
        if code == 429 or code >= 500:
            raise SendError(f"Telegram limita el envío: {description}", code="rate_limited", retryable=True)
        if code == 403:
            raise SendError(f"El usuario ha bloqueado el bot: {description}", code="blocked_by_user")
        raise SendError(f"Telegram rechazó la petición: {description}", code="rejected")

    # ------------------------------------------------------------------ inbound

    async def verify(self, ctx: ChannelContext, request: InboundRequest) -> None:
        supplied = request.header("x-telegram-bot-api-secret-token") or ""
        if not ctx.webhook_secret or not supplied or not hmac.compare_digest(supplied, ctx.webhook_secret):
            raise InvalidSignature("Token secreto de Telegram no válido")

    def parse(self, ctx: ChannelContext, request: InboundRequest) -> list[InboundMessage]:
        update = request.json()
        msg = update.get("message") if isinstance(update, dict) else None
        if not isinstance(msg, dict):
            return []
        sender = msg.get("from") or {}
        chat = msg.get("chat") or {}
        if sender.get("is_bot") or "id" not in chat or "message_id" not in msg:
            return []
        text, kind, attachments = _content(msg)
        chat_type = str(chat.get("type") or "private")
        username = str(ctx.config.get("bot_username") or "")
        if chat_type != "private" and ctx.config.get("group_mode", "mention") != "all":
            mention = f"@{username}".lower() if username else ""
            replied = ((msg.get("reply_to_message") or {}).get("from") or {}).get("username") == username
            if not username or not (mention in text.lower() or replied):
                return []
        if username:
            text = re.sub(rf"@{re.escape(username)}\b", "", text, flags=re.IGNORECASE).strip()
        if re.fullmatch(r"/start(@\w+)?(\s.*)?", text):
            text = text.split(maxsplit=1)[1] if " " in text else "Hola"
        if not text:
            return []
        name = " ".join(str(sender.get(k)) for k in ("first_name", "last_name") if sender.get(k)) or sender.get(
            "username"
        )
        sent_at = datetime.fromtimestamp(int(msg["date"]), UTC) if str(msg.get("date") or "").isdigit() else None
        return [
            InboundMessage(
                external_id=f"{chat['id']}:{msg['message_id']}",
                conversation_key=str(chat["id"]),
                sender_id=str(sender.get("id") or chat["id"]),
                sender_name=str(name) if name else None,
                text=text,
                kind=kind,
                attachments=attachments,
                reply={"chat_id": chat["id"], "message_id": msg["message_id"], "chat_type": chat_type},
                sent_at=sent_at,
            )
        ]

    # ------------------------------------------------------------------ outbound

    def format_text(self, markdown: str) -> str:
        return to_plain(markdown)

    async def send_text(self, ctx: ChannelContext, target: ReplyTarget, text: str) -> list[str]:
        chat_id = target.reply.get("chat_id") or target.conversation_key
        ids: list[str] = []
        for index, part in enumerate(self.parts(text)):
            body: dict[str, Any] = {"chat_id": chat_id, "text": part, "link_preview_options": {"is_disabled": True}}
            if index == 0 and target.reply.get("chat_type") not in (None, "private") and target.reply.get("message_id"):
                body["reply_parameters"] = {
                    "message_id": target.reply["message_id"],
                    "allow_sending_without_reply": True,
                }
            result = await self._call(ctx, "sendMessage", body)
            ids.append(f"{chat_id}:{(result or {}).get('message_id')}")
        return ids

    async def check(self, ctx: ChannelContext) -> CheckResult:
        if not ctx.credentials.get("bot_token"):
            raise InvalidConfig("Falta el token del bot de Telegram")
        me = await self._call(ctx, "getMe", {}) or {}
        info = await self._call(ctx, "getWebhookInfo", {}) or {}
        details = {
            "bot": f"@{me.get('username')}" if me.get("username") else None,
            "webhook_registered": bool(info.get("url")) and info.get("url") == ctx.webhook_url,
            "pending_updates": info.get("pending_update_count"),
            "last_error": info.get("last_error_message"),
        }
        updates = {"bot_username": me.get("username"), "bot_id": me.get("id")}
        return CheckResult(
            details={k: v for k, v in details.items() if v is not None},
            config_updates={k: v for k, v in updates.items() if v},
        )

    async def on_connect(self, ctx: ChannelContext) -> CheckResult:
        if not ctx.webhook_secret:
            raise InvalidConfig("El canal no tiene secreto de webhook")
        if not ctx.webhook_url.startswith("https://"):
            raise InvalidConfig(
                "Telegram solo acepta webhooks HTTPS públicos: configura MESSER_WEB_URL con una URL https"
            )
        await self._call(
            ctx,
            "setWebhook",
            {"url": ctx.webhook_url, "secret_token": ctx.webhook_secret, "allowed_updates": ALLOWED_UPDATES},
        )
        return await self.check(ctx)

    async def on_disconnect(self, ctx: ChannelContext) -> None:
        await self._call(ctx, "deleteWebhook", {"drop_pending_updates": False})
