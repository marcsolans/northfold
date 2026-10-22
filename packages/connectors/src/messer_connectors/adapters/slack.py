"""Slack: list channels, read history, post messages and search (Slack Web API, OAuth v2)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from ..base import (
    ActionSpec,
    Capabilities,
    ConnectionContext,
    ConnectorAuthError,
    ConnectorError,
    ConnectorSpec,
    OAuthSpec,
    ProviderError,
    RateLimitedError,
    obj_schema,
)
from ..demo import saas as demo_saas
from ..registry import register
from ..util import validate_args
from ._oauth import OAuthAdapter

AUTH_ERRORS = {"invalid_auth", "not_authed", "token_revoked", "token_expired", "account_inactive", "no_permission"}


def _ts_iso(ts: str | None) -> str | None:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(float(ts), UTC).isoformat()
    except ValueError:
        return None


@register
class SlackAdapter(OAuthAdapter):
    api_base = "https://slack.com/api"
    demo_handler = staticmethod(demo_saas.slack_handler)  # type: ignore[assignment]
    spec = ConnectorSpec(
        key="slack",
        name="Slack",
        category="communication",
        auth_type="oauth2",
        description="Publica mensajes, lista canales, lee conversaciones y busca en Slack.",
        description_en="Post messages, list channels, read conversations and search Slack.",
        icon="slack",
        oauth=OAuthSpec(
            provider="slack",
            authorize_url="https://slack.com/oauth/v2/authorize",
            token_url="https://slack.com/api/oauth.v2.access",
            scopes=[
                "channels:read",
                "groups:read",
                "channels:history",
                "groups:history",
                "chat:write",
                "chat:write.public",
            ],
            user_scopes=["search:read"],
            scope_separator=",",
            client_id_setting="slack_client_id",
            client_secret_setting="slack_client_secret",
            supports_refresh=True,
        ),
        capabilities=Capabilities(
            actions=["list_channels", "channel_history", "post_message", "update_message", "search_messages"],
            demo=True,
        ),
        docs_url="https://api.slack.com/web",
    )

    def check_response(self, res: httpx.Response) -> None:
        try:
            data = res.json()
        except ValueError:
            return
        if isinstance(data, dict) and data.get("ok") is False:
            error = str(data.get("error") or "unknown_error")
            if error in AUTH_ERRORS:
                raise ConnectorAuthError(f"Slack ha rechazado las credenciales ({error}). Vuelve a conectar Slack.")
            if error == "ratelimited":
                raise RateLimitedError("Slack limita las peticiones; inténtalo más tarde")
            if error == "missing_scope":
                raise ProviderError(
                    "Falta un permiso en la app de Slack (vuelve a conectar)", code="provider_forbidden"
                )
            raise ProviderError(f"Slack: {error}", details={"error": error})

    def actions(self) -> list[ActionSpec]:
        return [
            ActionSpec(
                name="list_channels",
                title="Listar canales",
                description="Canales públicos y privados accesibles.",
                input_schema=obj_schema({"limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200}}),
            ),
            ActionSpec(
                name="channel_history",
                title="Leer canal",
                description="Últimos mensajes de un canal.",
                input_schema=obj_schema(
                    {
                        "channel": {"type": "string", "minLength": 1, "description": "ID del canal"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 30},
                    },
                    ["channel"],
                ),
            ),
            ActionSpec(
                name="post_message",
                title="Publicar mensaje",
                description=(
                    "Publica un mensaje en un canal (o responde en un hilo). Admite bloques de Block Kit "
                    "(botones incluidos); «text» es el texto de notificación y de respaldo."
                ),
                input_schema=obj_schema(
                    {
                        "channel": {"type": "string", "minLength": 1, "description": "ID o #nombre del canal"},
                        "text": {"type": "string", "minLength": 1, "maxLength": 40000},
                        "blocks": {"type": "array", "items": {"type": "object"}, "maxItems": 50},
                        "thread_ts": {"type": "string"},
                        "unfurl_links": {"type": "boolean", "default": False},
                    },
                    ["channel", "text"],
                ),
                side_effect=True,
            ),
            ActionSpec(
                name="update_message",
                title="Actualizar mensaje",
                description="Sustituye el texto y los bloques de un mensaje publicado (p. ej. tras decidir una aprobación).",
                input_schema=obj_schema(
                    {
                        "channel": {"type": "string", "minLength": 1},
                        "ts": {"type": "string", "minLength": 1},
                        "text": {"type": "string", "minLength": 1, "maxLength": 40000},
                        "blocks": {"type": "array", "items": {"type": "object"}, "maxItems": 50},
                    },
                    ["channel", "ts", "text"],
                ),
                side_effect=True,
            ),
            ActionSpec(
                name="search_messages",
                title="Buscar mensajes",
                description="Busca mensajes en el espacio de trabajo (requiere el permiso de búsqueda del usuario).",
                input_schema=obj_schema(
                    {
                        "query": {"type": "string", "minLength": 1},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                    },
                    ["query"],
                ),
            ),
        ]

    async def whoami(self, ctx: ConnectionContext) -> dict[str, Any]:
        async with self.session(ctx) as api:
            data = await api.post("/auth.test")
        return {
            "account": data.get("team"),
            "name": data.get("user"),
            "team_id": data.get("team_id"),
            "url": data.get("url"),
        }

    async def run_action(self, ctx: ConnectionContext, action: str, args: dict[str, Any]) -> Any:
        data = validate_args(self.action(action), args)
        async with self.session(ctx) as api:
            if action == "list_channels":
                channels: list[dict[str, Any]] = []
                cursor = ""
                while True:
                    params: dict[str, Any] = {
                        "types": "public_channel,private_channel",
                        "exclude_archived": "true",
                        "limit": 200,
                    }
                    if cursor:
                        params["cursor"] = cursor
                    res = await api.get("/conversations.list", params=params)
                    channels.extend(res.get("channels", []))
                    cursor = ((res.get("response_metadata") or {}).get("next_cursor")) or ""
                    if not cursor or len(channels) >= int(data["limit"]):
                        break
                return [
                    {
                        "id": c.get("id"),
                        "name": c.get("name"),
                        "private": bool(c.get("is_private")),
                        "members": c.get("num_members"),
                        "topic": (c.get("topic") or {}).get("value"),
                    }
                    for c in channels[: int(data["limit"])]
                ]
            if action == "channel_history":
                res = await api.get(
                    "/conversations.history", params={"channel": data["channel"], "limit": int(data["limit"])}
                )
                return [
                    {"ts": m.get("ts"), "date": _ts_iso(m.get("ts")), "user": m.get("user"), "text": m.get("text")}
                    for m in res.get("messages", [])
                ]
            if action == "post_message":
                body: dict[str, Any] = {
                    "channel": data["channel"],
                    "text": data["text"],
                    "unfurl_links": bool(data["unfurl_links"]),
                }
                if data.get("blocks"):
                    body["blocks"] = data["blocks"]
                if data.get("thread_ts"):
                    body["thread_ts"] = data["thread_ts"]
                res = await api.post("/chat.postMessage", json=body)
                return {"channel": res.get("channel"), "ts": res.get("ts"), "status": "posted"}
            if action == "update_message":
                body = {"channel": data["channel"], "ts": data["ts"], "text": data["text"]}
                if data.get("blocks") is not None:
                    body["blocks"] = data["blocks"]
                res = await api.post("/chat.update", json=body)
                return {"channel": res.get("channel"), "ts": res.get("ts"), "status": "updated"}
            if action == "search_messages":
                user_token = (ctx.credentials.get("extra") or {}).get("user_token")
                if not ctx.demo and not user_token:
                    raise ConnectorError(
                        "La búsqueda necesita autorización de usuario de Slack (permiso search:read). Vuelve a conectar.",
                        code="missing_user_token",
                    )
                headers = {"Authorization": f"Bearer {user_token}"} if user_token else {}
                res = await api.get(
                    "/search.messages", params={"query": data["query"], "count": int(data["limit"])}, headers=headers
                )
                matches = (res.get("messages") or {}).get("matches", [])
                return [
                    {
                        "channel": (m.get("channel") or {}).get("name"),
                        "user": m.get("username"),
                        "text": m.get("text"),
                        "date": _ts_iso(m.get("ts")),
                        "url": m.get("permalink"),
                    }
                    for m in matches
                ]
        return await super().run_action(ctx, action, args)
