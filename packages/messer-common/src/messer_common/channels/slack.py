"""Slack (Events API + Web API).

* Requests are signed with the app's signing secret: ``X-Slack-Signature: v0=<hex hmac-sha256(secret,
  "v0:<timestamp>:<body>")>`` and ``X-Slack-Request-Timestamp`` within five minutes (replay protection).
* ``url_verification`` is answered with the challenge.
* ``app_mention`` in a channel starts (or continues) a thread conversation; direct messages (``message`` with
  ``channel_type = im``) are one conversation per DM; replies inside a thread the agent already takes part in
  are answered without a new mention. Bot messages, edits and other subtypes are ignored. Slack retries are
  harmless: every message is keyed by channel and ``ts``, so a retried or duplicated event (``app_mention`` and
  ``message`` for the same post) is processed once.
* Replies use ``chat.postMessage`` in the thread of the message.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import re
import time
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
from .formatting import to_slack

API_URL = "https://slack.com/api"
SIGNATURE_TOLERANCE_S = 300
AUTH_ERRORS = {"invalid_auth", "not_authed", "token_revoked", "token_expired", "account_inactive", "no_permission"}
ALLOWED_SUBTYPES = {None, "file_share", "thread_broadcast"}

_USER_MENTION = re.compile(r"<@([A-Z0-9]+)(?:\|[^>]*)?>")
_LINK = re.compile(r"<(https?://[^|>]+)\|([^>]+)>")
_BARE = re.compile(r"<(https?://[^>]+|mailto:[^>]+)>")
_CHANNEL_REF = re.compile(r"<#[A-Z0-9]+\|([^>]+)>")


def _clean_text(text: str, bot_user_id: str | None) -> tuple[str, bool]:
    """Slack markup → readable text. Returns (text, mentioned the bot)."""
    mentioned = bool(bot_user_id and f"<@{bot_user_id}" in text)
    if bot_user_id:
        text = re.sub(rf"<@{re.escape(bot_user_id)}(?:\|[^>]*)?>\s*", "", text)
    text = _USER_MENTION.sub(lambda m: f"@{m.group(1)}", text)
    text = _LINK.sub(lambda m: f"{m.group(2)} ({m.group(1)})", text)
    text = _BARE.sub(lambda m: m.group(1).removeprefix("mailto:"), text)
    text = _CHANNEL_REF.sub(lambda m: f"#{m.group(1)}", text)
    return html.unescape(text).strip(), mentioned


class SlackAdapter(ChannelAdapter):
    provider = "slack"
    label = "Slack"
    max_text = 3900
    credential_fields = (
        CredentialField("bot_token"),
        CredentialField("signing_secret", platform="slack_signing_secret"),
    )
    config_keys = ("bot_user_id", "team_id", "team_name", "bot_name")

    async def verify(self, ctx: ChannelContext, request: InboundRequest) -> None:
        secret = ctx.credentials.get("signing_secret")
        if not secret:
            raise InvalidSignature("El canal no tiene el Signing Secret de Slack configurado")
        timestamp = request.header("x-slack-request-timestamp") or ""
        signature = request.header("x-slack-signature") or ""
        if not timestamp.isdigit() or not signature.startswith("v0="):
            raise InvalidSignature("Faltan las cabeceras de firma de Slack")
        if abs(time.time() - int(timestamp)) > SIGNATURE_TOLERANCE_S:
            raise InvalidSignature("La firma de Slack ha caducado")
        base = f"v0:{timestamp}:".encode() + request.body
        expected = "v0=" + hmac.new(str(secret).encode(), base, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise InvalidSignature("Firma de Slack no válida")

    def immediate_reply(self, ctx: ChannelContext, request: InboundRequest) -> WebhookReply | None:
        data = request.json()
        if isinstance(data, dict) and data.get("type") == "url_verification":
            return WebhookReply(200, {"challenge": str(data.get("challenge") or "")})
        return None

    def parse(self, ctx: ChannelContext, request: InboundRequest) -> list[InboundMessage]:
        data = request.json()
        if not isinstance(data, dict) or data.get("type") != "event_callback":
            return []
        event = data.get("event") or {}
        bot_user = ctx.config.get("bot_user_id") or next(
            (a.get("user_id") for a in data.get("authorizations") or [] if a.get("is_bot")), None
        )
        user = event.get("user")
        if event.get("bot_id") or event.get("subtype") not in ALLOWED_SUBTYPES or not user or user == bot_user:
            return []
        channel = str(event.get("channel") or "")
        ts = str(event.get("ts") or "")
        if not channel or not ts:
            return []
        thread_ts = event.get("thread_ts")
        text, mentioned = _clean_text(str(event.get("text") or ""), bot_user)
        attachments = [
            {"type": "file", "id": f.get("id"), "name": f.get("name"), "mime_type": f.get("mimetype")}
            for f in event.get("files") or []
        ]
        if attachments:
            names = ", ".join(str(a.get("name") or "archivo") for a in attachments)
            text = f"{text}\n[Archivos adjuntos: {names}]".strip()
        if not text:
            return []
        kind = str(event.get("type") or "")
        requires_existing = False
        if kind == "app_mention":
            root = str(thread_ts or ts)
            key, reply = f"thread:{channel}:{root}", {"channel": channel, "thread_ts": root}
        elif kind == "message" and event.get("channel_type") == "im":
            key, reply = f"dm:{channel}", {"channel": channel, "thread_ts": thread_ts}
        elif kind == "message" and thread_ts:
            key, reply = f"thread:{channel}:{thread_ts}", {"channel": channel, "thread_ts": str(thread_ts)}
            requires_existing = not mentioned
        else:
            return []
        team = str(data.get("team_id") or event.get("team") or "")
        return [
            InboundMessage(
                external_id=f"{channel}:{ts}",
                conversation_key=key,
                sender_id=str(user),
                sender_name=None,
                text=text,
                kind="media" if attachments else "text",
                attachments=attachments,
                thread_id=reply.get("thread_ts"),
                reply={**reply, "team_id": team},
                requires_existing_conversation=requires_existing,
            )
        ]

    # ------------------------------------------------------------------ outbound

    def format_text(self, markdown: str) -> str:
        return to_slack(markdown)

    def _headers(self, ctx: ChannelContext) -> dict[str, str]:
        token = ctx.credentials.get("bot_token")
        if not token:
            raise SendError("Falta el Bot Token de Slack", code="missing_credentials", auth=True)
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}

    async def _call(self, ctx: ChannelContext, method: str, body: dict[str, Any]) -> dict[str, Any]:
        res = await http.request("POST", f"{API_URL}/{method}", provider="Slack", json=body, headers=self._headers(ctx))
        if res.status_code == 429:
            raise SendError("Slack limita el envío de mensajes", code="rate_limited", retryable=True)
        http.raise_for_send(res, "Slack")
        try:
            data = res.json()
        except ValueError as exc:
            raise SendError("Slack devolvió una respuesta no válida", code="bad_response", retryable=True) from exc
        if not data.get("ok"):
            error = str(data.get("error") or "unknown_error")
            if error in AUTH_ERRORS:
                raise SendError(f"Slack rechazó el token del bot ({error})", code="auth_failed", auth=True)
            if error == "ratelimited":
                raise SendError("Slack limita el envío de mensajes", code="rate_limited", retryable=True)
            raise SendError(f"Slack rechazó el mensaje ({error})", code=error[:60])
        return data

    async def send_text(self, ctx: ChannelContext, target: ReplyTarget, text: str) -> list[str]:
        channel = target.reply.get("channel")
        if not channel:
            raise SendError("No se sabe a qué conversación de Slack responder", code="missing_target")
        ids: list[str] = []
        for part in self.parts(text):
            body: dict[str, Any] = {"channel": channel, "text": part, "unfurl_links": False, "unfurl_media": False}
            if target.reply.get("thread_ts"):
                body["thread_ts"] = target.reply["thread_ts"]
            data = await self._call(ctx, "chat.postMessage", body)
            ids.append(f"{data.get('channel') or channel}:{data.get('ts')}")
        return ids

    async def check(self, ctx: ChannelContext) -> CheckResult:
        if not ctx.credentials.get("bot_token"):
            raise InvalidConfig("Falta el Bot Token de Slack")
        data = await self._call(ctx, "auth.test", {})
        updates = {
            "bot_user_id": data.get("user_id"),
            "team_id": data.get("team_id"),
            "team_name": data.get("team"),
            "bot_name": data.get("user"),
        }
        updates = {k: v for k, v in updates.items() if v}
        return CheckResult(details={"team": data.get("team"), "bot": data.get("user")}, config_updates=updates)
