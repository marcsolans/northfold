"""Microsoft Teams (Azure Bot Service / Bot Framework).

* Inbound activities carry ``Authorization: Bearer <JWT>`` issued by the Bot Connector. The token is validated
  against the Bot Framework OpenID metadata (signing keys from its JWKS), with issuer
  ``https://api.botframework.com``, audience = the bot's Microsoft App ID, and the ``serviceurl`` claim equal to
  the activity's ``serviceUrl`` (so replies only go to the service that called us).
* ``message`` activities become inbound messages (``<at>`` mentions removed); other activity types are ignored.
* Replies: client-credentials token for ``https://api.botframework.com/.default``, then
  ``POST {serviceUrl}/v3/conversations/{conversationId}/activities/{activityId}`` with Markdown text.
"""

from __future__ import annotations

import hashlib
import html
import re
import time
from typing import Any
from urllib.parse import quote, urlparse

import jwt

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

OPENID_CONFIG_URL = "https://login.botframework.com/v1/.well-known/openidconfiguration"
ISSUER = "https://api.botframework.com"
TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"  # noqa: S105 (endpoint, not a secret)
TOKEN_SCOPE = "https://api.botframework.com/.default"  # noqa: S105 (OAuth scope, not a secret)
JWKS_TTL_S = 24 * 3600
JWKS_REFRESH_MIN_S = 300
CLOCK_SKEW_S = 300
MAX_KEY_LEN = 200

_jwks: dict[str, Any] = {"keys": {}, "fetched": 0.0}
_tokens: dict[str, tuple[str, float]] = {}

_AT_TAG = re.compile(r"<at>.*?</at>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")


def reset_caches() -> None:
    """Forget cached signing keys and access tokens (tests, key rotation)."""
    _jwks.update({"keys": {}, "fetched": 0.0})
    _tokens.clear()


async def _fetch_jwks() -> dict[str, dict[str, Any]]:
    res = await http.request("GET", OPENID_CONFIG_URL, provider="Bot Framework")
    if res.status_code >= 400:
        raise InvalidSignature("No se pudo leer la configuración OpenID de Bot Framework")
    jwks_uri = res.json().get("jwks_uri")
    if not jwks_uri:
        raise InvalidSignature("La configuración OpenID de Bot Framework no tiene jwks_uri")
    keys_res = await http.request("GET", str(jwks_uri), provider="Bot Framework")
    if keys_res.status_code >= 400:
        raise InvalidSignature("No se pudieron leer las claves de firma de Bot Framework")
    return {str(k["kid"]): k for k in keys_res.json().get("keys") or [] if k.get("kid")}


async def _signing_key(kid: str) -> dict[str, Any]:
    now = time.time()
    keys: dict[str, dict[str, Any]] = _jwks["keys"]
    stale = now - float(_jwks["fetched"]) > JWKS_TTL_S
    unknown = kid not in keys and now - float(_jwks["fetched"]) > JWKS_REFRESH_MIN_S
    if stale or unknown or not keys:
        try:
            keys = await _fetch_jwks()
        except SendError as exc:
            raise InvalidSignature("No se pudo contactar con Bot Framework para validar el token") from exc
        _jwks.update({"keys": keys, "fetched": now})
    key = keys.get(kid)
    if key is None:
        raise InvalidSignature("El token de Bot Framework está firmado con una clave desconocida")
    return key


def _short_key(value: str) -> str:
    return value if len(value) <= MAX_KEY_LEN else "h:" + hashlib.sha256(value.encode()).hexdigest()


class TeamsAdapter(ChannelAdapter):
    provider = "teams"
    label = "Microsoft Teams"
    max_text = 7000
    credential_fields = (CredentialField("app_password", platform="teams_app_password"),)
    config_keys = ("app_id", "tenant_id", "bot_name")
    platform_config = {"app_id": "teams_app_id"}
    required_config = ("app_id",)

    def provider_config(self, config: dict[str, Any]) -> dict[str, Any]:
        out = super().provider_config(config)
        for key in ("app_id", "tenant_id"):
            if key in out and not re.fullmatch(r"[0-9a-fA-F-]{36}|[a-z0-9.-]+\.[a-z]{2,}", str(out[key]).strip()):
                raise ValueError(f"«{key}» debe ser un identificador (GUID) de Microsoft Entra")
            if key in out:
                out[key] = str(out[key]).strip()
        return out

    # ------------------------------------------------------------------ inbound

    async def verify(self, ctx: ChannelContext, request: InboundRequest) -> None:
        app_id = ctx.config.get("app_id")
        if not app_id:
            raise InvalidSignature("El canal no tiene el Microsoft App ID configurado")
        header = request.header("authorization") or ""
        if not header.lower().startswith("bearer "):
            raise InvalidSignature("Falta el token de Bot Framework")
        token = header[7:].strip()
        try:
            kid = str(jwt.get_unverified_header(token).get("kid") or "")
        except jwt.PyJWTError as exc:
            raise InvalidSignature("Token de Bot Framework mal formado") from exc
        jwk = await _signing_key(kid)
        activity = request.json()
        channel_id = (activity or {}).get("channelId") if isinstance(activity, dict) else None
        endorsements = jwk.get("endorsements")
        if channel_id and isinstance(endorsements, list) and endorsements and channel_id not in endorsements:
            raise InvalidSignature("La clave de firma no está autorizada para este canal")
        try:
            key = jwt.PyJWK(jwk).key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=str(app_id),
                issuer=ISSUER,
                leeway=CLOCK_SKEW_S,
                options={"require": ["exp", "iss", "aud"]},
            )
        except jwt.PyJWTError as exc:
            raise InvalidSignature(f"Token de Bot Framework no válido: {type(exc).__name__}") from exc
        service_url = str((activity or {}).get("serviceUrl") or "") if isinstance(activity, dict) else ""
        claimed = str(claims.get("serviceurl") or claims.get("serviceUrl") or "")
        if claimed and service_url and claimed.rstrip("/") != service_url.rstrip("/"):
            raise InvalidSignature("El serviceUrl de la actividad no coincide con el del token")
        if service_url and urlparse(service_url).scheme != "https":
            raise InvalidSignature("El serviceUrl debe usar HTTPS")

    def parse(self, ctx: ChannelContext, request: InboundRequest) -> list[InboundMessage]:
        activity = request.json()
        if not isinstance(activity, dict) or activity.get("type") != "message":
            return []
        sender = activity.get("from") or {}
        recipient = activity.get("recipient") or {}
        if sender.get("role") == "bot" or (sender.get("id") and sender.get("id") == recipient.get("id")):
            return []
        conversation = activity.get("conversation") or {}
        conversation_id = str(conversation.get("id") or "")
        activity_id = str(activity.get("id") or "")
        service_url = str(activity.get("serviceUrl") or "")
        if not conversation_id or not activity_id or not service_url:
            return []
        raw = str(activity.get("text") or "")
        text = html.unescape(_TAG.sub("", _AT_TAG.sub("", raw))).strip()
        attachments = [
            {"type": "file", "name": a.get("name"), "mime_type": a.get("contentType")}
            for a in activity.get("attachments") or []
            if a.get("contentType") not in ("text/html", "application/vnd.microsoft.teams.card.o365connector")
        ]
        if attachments:
            names = ", ".join(str(a.get("name") or "archivo") for a in attachments)
            text = f"{text}\n[Archivos adjuntos: {names}]".strip()
        if not text:
            return []
        return [
            InboundMessage(
                external_id=_short_key(f"{conversation_id}:{activity_id}"),
                conversation_key=_short_key(conversation_id),
                sender_id=str(sender.get("aadObjectId") or sender.get("id") or ""),
                sender_name=sender.get("name"),
                text=text,
                kind="media" if attachments else "text",
                attachments=attachments,
                thread_id=conversation_id if conversation.get("conversationType") == "channel" else None,
                reply={
                    "service_url": service_url,
                    "conversation_id": conversation_id,
                    "activity_id": activity_id,
                    "bot": {"id": recipient.get("id"), "name": recipient.get("name")},
                    "user": {"id": sender.get("id"), "name": sender.get("name")},
                    "tenant_id": conversation.get("tenantId"),
                },
            )
        ]

    # ------------------------------------------------------------------ outbound

    async def _token(self, ctx: ChannelContext) -> str:
        app_id = str(ctx.config.get("app_id") or "")
        password = ctx.credentials.get("app_password")
        if not app_id or not password:
            raise SendError("Faltan el App ID o la contraseña del bot de Teams", code="missing_credentials", auth=True)
        cached = _tokens.get(app_id)
        if cached and cached[1] > time.time() + 60:
            return cached[0]
        tenant = ctx.config.get("tenant_id") or "botframework.com"
        res = await http.request(
            "POST",
            TOKEN_URL.format(tenant=quote(str(tenant), safe="")),
            provider="Microsoft Entra",
            data={
                "grant_type": "client_credentials",
                "client_id": app_id,
                "client_secret": password,
                "scope": TOKEN_SCOPE,
            },
        )
        if res.status_code in (400, 401):
            raise SendError("Microsoft rechazó el App ID o la contraseña del bot", code="auth_failed", auth=True)
        http.raise_for_send(res, "Microsoft Entra")
        data = res.json()
        token = str(data.get("access_token") or "")
        if not token:
            raise SendError("Microsoft no devolvió un token de acceso", code="auth_failed", auth=True)
        _tokens[app_id] = (token, time.time() + float(data.get("expires_in") or 3600))
        return token

    async def send_text(self, ctx: ChannelContext, target: ReplyTarget, text: str) -> list[str]:
        reply = target.reply
        service_url = str(reply.get("service_url") or "")
        conversation_id = str(reply.get("conversation_id") or "")
        if not service_url.startswith("https://") or not conversation_id:
            raise SendError("No se sabe a qué conversación de Teams responder", code="missing_target")
        token = await self._token(ctx)
        activity_id = str(reply.get("activity_id") or "")
        base = f"{service_url.rstrip('/')}/v3/conversations/{quote(conversation_id, safe='')}/activities"
        url = f"{base}/{quote(activity_id, safe='')}" if activity_id else base
        ids: list[str] = []
        for part in self.parts(text):
            body: dict[str, Any] = {
                "type": "message",
                "text": part,
                "textFormat": "markdown",
                "conversation": {"id": conversation_id},
            }
            if reply.get("bot"):
                body["from"] = reply["bot"]
            if reply.get("user"):
                body["recipient"] = reply["user"]
            if activity_id:
                body["replyToId"] = activity_id
            res = await http.request(
                "POST", url, provider="Teams", json=body, headers={"Authorization": f"Bearer {token}"}
            )
            if res.status_code == 401:
                _tokens.pop(str(ctx.config.get("app_id") or ""), None)
            http.raise_for_send(res, "Teams")
            try:
                ids.append(str(res.json().get("id") or ""))
            except ValueError:
                ids.append("")
        return [i for i in ids if i]

    async def check(self, ctx: ChannelContext) -> CheckResult:
        if not ctx.config.get("app_id"):
            raise InvalidConfig("Falta el Microsoft App ID del bot")
        _tokens.pop(str(ctx.config["app_id"]), None)
        await self._token(ctx)
        return CheckResult(details={"app_id": ctx.config["app_id"]})
