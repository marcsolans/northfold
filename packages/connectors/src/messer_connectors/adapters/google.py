"""Google Drive, Gmail and Google Calendar (Google APIs, OAuth 2 with offline access)."""

from __future__ import annotations

import asyncio
import base64
import time
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import getaddresses
from typing import Any

from messer_common.settings import get_settings

from ..base import (
    ActionSpec,
    Capabilities,
    ConnectionContext,
    ConnectorError,
    ConnectorSpec,
    OAuthSpec,
    ProviderError,
    Resource,
    SyncFile,
    SyncOutcome,
    SyncRequest,
    SyncSink,
    obj_schema,
)
from ..demo import google as demo_google
from ..registry import register
from ..util import html_to_text, safe_filename, to_rfc3339, truncate, validate_args
from ._oauth import ApiSession, OAuthAdapter

GOOGLE_AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"  # noqa: S105 - URL, not a secret
USERINFO_SCOPE = "https://www.googleapis.com/auth/userinfo.email"


def google_oauth(scopes: list[str]) -> OAuthSpec:
    return OAuthSpec(
        provider="google",
        authorize_url=GOOGLE_AUTHORIZE,
        token_url=GOOGLE_TOKEN,
        scopes=[USERINFO_SCOPE, *scopes],
        client_id_setting="google_client_id",
        client_secret_setting="google_client_secret",
        pkce=True,
        extra_authorize_params={"access_type": "offline", "prompt": "consent", "include_granted_scopes": "true"},
    )


class GoogleAdapter(OAuthAdapter):
    demo_handler = staticmethod(demo_google.handler)  # type: ignore[assignment]


# ============================================================================= Drive

FOLDER_MIME = "application/vnd.google-apps.folder"
EXPORTS: dict[str, tuple[str, str]] = {
    "application/vnd.google-apps.document": ("text/markdown", ".md"),
    "application/vnd.google-apps.spreadsheet": ("text/csv", ".csv"),
    "application/vnd.google-apps.presentation": ("text/plain", ".txt"),
}
FILE_FIELDS = "id,name,mimeType,parents,createdTime,modifiedTime,size,md5Checksum,version,webViewLink,trashed"
LIST_COMMON = {"supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}


def _q_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


@register
class GoogleDriveAdapter(GoogleAdapter):
    api_base = "https://www.googleapis.com"
    spec = ConnectorSpec(
        key="google_drive",
        name="Google Drive",
        category="files",
        auth_type="oauth2",
        description="Carpetas y archivos de Drive; exporta Docs y Sheets y sincroniza carpetas con el conocimiento.",
        description_en="Drive folders and files; exports Docs and Sheets and syncs folders into knowledge bases.",
        icon="google-drive",
        oauth=google_oauth(["https://www.googleapis.com/auth/drive.readonly"]),
        capabilities=Capabilities(
            actions=["list_folders", "list_files", "search_files", "get_file"],
            sync=True,
            sync_resources=["folder"],
            events=["new_file"],
            demo=True,
        ),
        docs_url="https://developers.google.com/drive/api/guides/about-sdk",
    )

    def actions(self) -> list[ActionSpec]:
        return [
            ActionSpec(
                name="list_folders",
                title="Listar carpetas",
                description="Carpetas dentro de una carpeta de Drive («root» para Mi unidad).",
                input_schema=obj_schema({"folder_id": {"type": "string", "default": "root"}}),
            ),
            ActionSpec(
                name="list_files",
                title="Listar archivos",
                description="Archivos de una carpeta de Drive.",
                input_schema=obj_schema(
                    {
                        "folder_id": {"type": "string", "default": "root"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                    }
                ),
            ),
            ActionSpec(
                name="search_files",
                title="Buscar archivos",
                description="Busca archivos por nombre o contenido.",
                input_schema=obj_schema(
                    {
                        "query": {"type": "string", "minLength": 1},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                    },
                    ["query"],
                ),
            ),
            ActionSpec(
                name="get_file",
                title="Leer archivo",
                description="Devuelve el texto de un archivo (Docs se exporta a Markdown y Sheets a CSV).",
                input_schema=obj_schema({"file_id": {"type": "string", "minLength": 1}}, ["file_id"]),
            ),
        ]

    async def whoami(self, ctx: ConnectionContext) -> dict[str, Any]:
        async with self.session(ctx) as api:
            data = await api.get("/drive/v3/about", params={"fields": "user"})
        user = data.get("user") or {}
        return {"email": user.get("emailAddress"), "name": user.get("displayName")}

    async def _list(
        self, api: ApiSession, q: str, *, limit: int | None = None, order_by: str | None = None
    ) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        token: str | None = None
        while True:
            params: dict[str, Any] = {
                "q": q,
                "fields": f"nextPageToken,files({FILE_FIELDS})",
                "pageSize": min(limit or 200, 200),
                **LIST_COMMON,
            }
            if order_by:
                params["orderBy"] = order_by
            if token:
                params["pageToken"] = token
            data = await api.get("/drive/v3/files", params=params)
            files.extend(data.get("files", []))
            token = data.get("nextPageToken")
            if not token or (limit is not None and len(files) >= limit):
                return files[:limit] if limit else files

    async def _content(self, api: ApiSession, meta: dict[str, Any]) -> tuple[bytes, str, str]:
        """(bytes, mime, filename) — Google-native files are exported."""
        mime = str(meta.get("mimeType", ""))
        name = safe_filename(str(meta.get("name", "documento")))
        if mime in EXPORTS:
            export_mime, ext = EXPORTS[mime]
            try:
                res = await api.call(
                    "GET", f"/drive/v3/files/{meta['id']}/export", params={"mimeType": export_mime}, raw=True
                )
            except ProviderError:
                if export_mime != "text/markdown":
                    raise
                export_mime, ext = "text/plain", ".txt"
                res = await api.call(
                    "GET", f"/drive/v3/files/{meta['id']}/export", params={"mimeType": export_mime}, raw=True
                )
            return res.content, export_mime, name if name.lower().endswith(ext) else f"{name}{ext}"
        if mime.startswith("application/vnd.google-apps"):
            raise ConnectorError(f"El tipo {mime} no se puede exportar", code="unsupported_file")
        res = await api.call("GET", f"/drive/v3/files/{meta['id']}", params={"alt": "media", **LIST_COMMON}, raw=True)
        return res.content, mime or "application/octet-stream", name

    async def run_action(self, ctx: ConnectionContext, action: str, args: dict[str, Any]) -> Any:
        data = validate_args(self.action(action), args)
        async with self.session(ctx) as api:
            if action == "list_folders":
                q = f"'{_q_escape(data['folder_id'])}' in parents and mimeType = '{FOLDER_MIME}' and trashed = false"
                return [_file_out(f) for f in await self._list(api, q, order_by="name")]
            if action == "list_files":
                q = f"'{_q_escape(data['folder_id'])}' in parents and trashed = false"
                return [
                    _file_out(f) for f in await self._list(api, q, limit=int(data["limit"]), order_by="folder,name")
                ]
            if action == "search_files":
                term = _q_escape(data["query"])
                q = f"(name contains '{term}' or fullText contains '{term}') and trashed = false"
                return [_file_out(f) for f in await self._list(api, q, limit=int(data["limit"]))]
            if action == "get_file":
                meta = await api.get(
                    f"/drive/v3/files/{data['file_id']}", params={"fields": FILE_FIELDS, **LIST_COMMON}
                )
                content, mime, filename = await self._content(api, meta)
                out = _file_out(meta)
                if mime.startswith("text/") or mime in ("application/json",):
                    out["content"] = truncate(content.decode("utf-8", "replace"), 50_000)
                else:
                    out["content"] = None
                    out["note"] = "Archivo binario: sincroniza la carpeta con una base de conocimiento para indexarlo."
                out["exported_as"] = mime
                out["filename"] = filename
                return out
        return await super().run_action(ctx, action, args)

    async def list_resources(self, ctx: ConnectionContext, parent: str | None = None) -> list[Resource]:
        folder = (parent or "folder:root").removeprefix("folder:")
        out: list[Resource] = []
        if parent is None:
            out.append(Resource(id="folder:root", name="Mi unidad", kind="folder", has_children=True))
        async with self.session(ctx) as api:
            q = f"'{_q_escape(folder)}' in parents and mimeType = '{FOLDER_MIME}' and trashed = false"
            for f in await self._list(api, q, order_by="name"):
                out.append(
                    Resource(
                        id=f"folder:{f['id']}",
                        name=f["name"],
                        kind="folder",
                        has_children=True,
                        parent=f"folder:{folder}",
                    )
                )
        return out

    async def sync(self, ctx: ConnectionContext, request: SyncRequest, sink: SyncSink) -> SyncOutcome:
        root = request.resource.removeprefix("folder:") or "root"
        recursive = request.options.get("recursive", True) is not False
        since = request.cursor if request.mode == "incremental" else None
        max_bytes = get_settings().messer_connectors_max_file_mb * 1024 * 1024
        stats = {"files": 0, "skipped": 0, "unsupported": 0, "too_large": 0, "folders": 0}
        newest = since
        queue: list[tuple[str, str]] = [(root, "")]
        seen: set[str] = set()
        async with self.session(ctx) as api:
            while queue:
                folder_id, prefix = queue.pop(0)
                if folder_id in seen:
                    continue
                seen.add(folder_id)
                stats["folders"] += 1
                q = f"'{_q_escape(folder_id)}' in parents and trashed = false"
                for meta in await self._list(api, q):
                    mime = str(meta.get("mimeType", ""))
                    if mime == FOLDER_MIME:
                        if recursive:
                            queue.append((meta["id"], f"{prefix}{meta['name']}/"))
                        continue
                    modified = str(meta.get("modifiedTime") or "")
                    if since and modified and modified <= since:
                        stats["skipped"] += 1
                        continue
                    if newest is None or modified > newest:
                        newest = modified
                    if mime.startswith("application/vnd.google-apps") and mime not in EXPORTS:
                        stats["unsupported"] += 1
                        continue
                    if int(meta.get("size") or 0) > max_bytes:
                        stats["too_large"] += 1
                        continue
                    version = str(meta.get("version") or modified)
                    if await sink.should_skip(meta["id"], version):
                        stats["skipped"] += 1
                        continue
                    content, export_mime, filename = await self._content(api, meta)
                    await sink.file(
                        SyncFile(
                            external_id=meta["id"],
                            filename=filename,
                            data=content,
                            mime=export_mime,
                            version=version,
                            modified_at=modified or None,
                            url=meta.get("webViewLink"),
                            path=f"{prefix}{filename}",
                        )
                    )
                    stats["files"] += 1
        return SyncOutcome(next_cursor=newest, stats=stats)

    async def poll_events(
        self, ctx: ConnectionContext, event: str, cursor: str | None
    ) -> tuple[list[dict[str, Any]], str | None]:
        self._check_event(event)
        folder = event.split(":", 1)[1] if ":" in event else ctx.config.get("event_folder_id")
        if cursor is None:
            return [], to_rfc3339(datetime.now(UTC))
        q = f"createdTime > '{cursor}' and trashed = false and mimeType != '{FOLDER_MIME}'"
        if folder:
            q = f"'{_q_escape(str(folder))}' in parents and {q}"
        async with self.session(ctx) as api:
            files = await self._list(api, q, limit=100, order_by="createdTime")
        events = [
            {"id": f["id"], "event": "new_file", "occurred_at": f.get("createdTime"), "data": _file_out(f)}
            for f in files
        ]
        newest = max((str(f.get("createdTime")) for f in files), default=cursor)
        return events, newest


def _file_out(meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": meta.get("id"),
        "name": meta.get("name"),
        "mime_type": meta.get("mimeType"),
        "is_folder": meta.get("mimeType") == FOLDER_MIME,
        "size": int(meta["size"]) if meta.get("size") else None,
        "modified_at": meta.get("modifiedTime"),
        "created_at": meta.get("createdTime"),
        "url": meta.get("webViewLink"),
    }


# ============================================================================= Gmail


def _header(headers: list[dict[str, str]], name: str) -> str | None:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value")
    return None


def _decode_b64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _gmail_body(payload: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    plain: list[str] = []
    html: list[str] = []
    attachments: list[dict[str, Any]] = []

    def walk(part: dict[str, Any]) -> None:
        mime = part.get("mimeType", "")
        body = part.get("body") or {}
        if part.get("filename"):
            attachments.append(
                {
                    "filename": part["filename"],
                    "mime_type": mime,
                    "size": body.get("size"),
                    "attachment_id": body.get("attachmentId"),
                }
            )
        elif mime == "text/plain" and body.get("data"):
            plain.append(_decode_b64(body["data"]).decode("utf-8", "replace"))
        elif mime == "text/html" and body.get("data"):
            html.append(_decode_b64(body["data"]).decode("utf-8", "replace"))
        for sub in part.get("parts") or []:
            walk(sub)

    walk(payload)
    text = "\n".join(plain) if plain else html_to_text("\n".join(html))
    return text, attachments


def _gmail_summary(msg: dict[str, Any]) -> dict[str, Any]:
    headers = (msg.get("payload") or {}).get("headers") or []
    internal = msg.get("internalDate")
    return {
        "id": msg.get("id"),
        "thread_id": msg.get("threadId"),
        "from": _header(headers, "From"),
        "to": _header(headers, "To"),
        "subject": _header(headers, "Subject"),
        "date": datetime.fromtimestamp(int(internal) / 1000, UTC).isoformat() if internal else _header(headers, "Date"),
        "snippet": msg.get("snippet"),
        "labels": msg.get("labelIds", []),
        "unread": "UNREAD" in (msg.get("labelIds") or []),
    }


def _mime(to: list[str], subject: str, body: str, cc: list[str] | None, reply_to_id: str | None) -> str:
    message = EmailMessage()
    message["To"] = ", ".join(to)
    if cc:
        message["Cc"] = ", ".join(cc)
    message["Subject"] = subject
    if reply_to_id:
        message["In-Reply-To"] = reply_to_id
        message["References"] = reply_to_id
    message.set_content(body)
    return base64.urlsafe_b64encode(message.as_bytes()).decode()


_EMAIL_LIST = {"type": "array", "items": {"type": "string", "format": "email"}, "minItems": 1}


@register
class GmailAdapter(GoogleAdapter):
    api_base = "https://gmail.googleapis.com"
    spec = ConnectorSpec(
        key="gmail",
        name="Gmail",
        category="communication",
        auth_type="oauth2",
        description="Busca y lee correos, crea borradores y envía mensajes desde Gmail.",
        description_en="Search and read email, create drafts and send messages from Gmail.",
        icon="gmail",
        oauth=google_oauth(
            [
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.compose",
                "https://www.googleapis.com/auth/gmail.send",
            ]
        ),
        capabilities=Capabilities(
            actions=["search_messages", "get_message", "create_draft", "send_message", "send_draft"],
            events=["new_email"],
            demo=True,
        ),
        docs_url="https://developers.google.com/gmail/api/guides",
    )

    def actions(self) -> list[ActionSpec]:
        compose = {
            "to": _EMAIL_LIST,
            "cc": {"type": "array", "items": {"type": "string", "format": "email"}},
            "subject": {"type": "string", "minLength": 1, "maxLength": 998},
            "body": {"type": "string"},
            "in_reply_to": {"type": "string", "description": "Message-ID al que se responde"},
            "thread_id": {"type": "string"},
        }
        return [
            ActionSpec(
                name="search_messages",
                title="Buscar correos",
                description="Busca correos con la sintaxis de Gmail (p. ej. «from:cliente factura is:unread»).",
                input_schema=obj_schema(
                    {
                        "query": {"type": "string", "default": "in:inbox"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                    }
                ),
            ),
            ActionSpec(
                name="get_message",
                title="Leer correo",
                description="Devuelve remitente, asunto, cuerpo en texto y adjuntos de un correo.",
                input_schema=obj_schema({"message_id": {"type": "string", "minLength": 1}}, ["message_id"]),
            ),
            ActionSpec(
                name="create_draft",
                title="Crear borrador",
                description="Crea un borrador en Gmail sin enviarlo.",
                input_schema=obj_schema(compose, ["to", "subject", "body"]),
                side_effect=True,
            ),
            ActionSpec(
                name="send_message",
                title="Enviar correo",
                description="Envía un correo desde la cuenta conectada.",
                input_schema=obj_schema(compose, ["to", "subject", "body"]),
                side_effect=True,
            ),
            ActionSpec(
                name="send_draft",
                title="Enviar borrador",
                description="Envía un borrador existente.",
                input_schema=obj_schema({"draft_id": {"type": "string", "minLength": 1}}, ["draft_id"]),
                side_effect=True,
            ),
        ]

    async def whoami(self, ctx: ConnectionContext) -> dict[str, Any]:
        async with self.session(ctx) as api:
            data = await api.get("/gmail/v1/users/me/profile")
        return {"email": data.get("emailAddress"), "messages": data.get("messagesTotal")}

    async def _metadata(self, api: ApiSession, ids: list[str]) -> list[dict[str, Any]]:
        sem = asyncio.Semaphore(8)

        async def one(mid: str) -> dict[str, Any]:
            async with sem:
                return await api.get(
                    f"/gmail/v1/users/me/messages/{mid}",
                    params=[
                        ("format", "metadata"),
                        *(("metadataHeaders", h) for h in ("From", "To", "Subject", "Date")),
                    ],
                )

        return list(await asyncio.gather(*(one(i) for i in ids)))

    async def run_action(self, ctx: ConnectionContext, action: str, args: dict[str, Any]) -> Any:
        data = validate_args(self.action(action), args)
        async with self.session(ctx) as api:
            if action == "search_messages":
                listing = await api.get(
                    "/gmail/v1/users/me/messages", params={"q": data["query"], "maxResults": int(data["limit"])}
                )
                ids = [m["id"] for m in listing.get("messages", [])]
                return [_gmail_summary(m) for m in await self._metadata(api, ids)]
            if action == "get_message":
                msg = await api.get(f"/gmail/v1/users/me/messages/{data['message_id']}", params={"format": "full"})
                out = _gmail_summary(msg)
                body, attachments = _gmail_body(msg.get("payload") or {})
                out["body"] = truncate(body, 50_000)
                out["attachments"] = attachments
                out["cc"] = _header((msg.get("payload") or {}).get("headers") or [], "Cc")
                return out
            if action in ("create_draft", "send_message"):
                raw = _mime(data["to"], data["subject"], data.get("body", ""), data.get("cc"), data.get("in_reply_to"))
                message: dict[str, Any] = {"raw": raw}
                if data.get("thread_id"):
                    message["threadId"] = data["thread_id"]
                if action == "create_draft":
                    res = await api.post("/gmail/v1/users/me/drafts", json={"message": message})
                    return {
                        "draft_id": res.get("id"),
                        "message_id": (res.get("message") or {}).get("id"),
                        "status": "draft",
                    }
                res = await api.post("/gmail/v1/users/me/messages/send", json=message)
                return {"message_id": res.get("id"), "thread_id": res.get("threadId"), "status": "sent"}
            if action == "send_draft":
                res = await api.post("/gmail/v1/users/me/drafts/send", json={"id": data["draft_id"]})
                return {"message_id": res.get("id"), "thread_id": res.get("threadId"), "status": "sent"}
        return await super().run_action(ctx, action, args)

    async def poll_events(
        self, ctx: ConnectionContext, event: str, cursor: str | None
    ) -> tuple[list[dict[str, Any]], str | None]:
        self._check_event(event)
        if cursor is None:
            return [], str(int(time.time() * 1000))
        since_ms = int(cursor)
        query = f"in:inbox after:{max(since_ms // 1000 - 60, 0)}"
        if ctx.config.get("event_query"):
            query = f"{query} {ctx.config['event_query']}"
        async with self.session(ctx) as api:
            listing = await api.get("/gmail/v1/users/me/messages", params={"q": query, "maxResults": 50})
            ids = [m["id"] for m in listing.get("messages", [])]
            metas = await self._metadata(api, ids)
        fresh = sorted(
            (m for m in metas if int(m.get("internalDate") or 0) > since_ms),
            key=lambda m: int(m.get("internalDate") or 0),
        )
        events = []
        for m in fresh:
            summary = _gmail_summary(m)
            senders = getaddresses([summary.get("from") or ""])
            summary["from_email"] = senders[0][1] if senders else None
            events.append({"id": m["id"], "event": "new_email", "occurred_at": summary["date"], "data": summary})
        newest = max((int(m.get("internalDate") or 0) for m in fresh), default=since_ms)
        return events, str(newest)


# ============================================================================= Calendar


@register
class GoogleCalendarAdapter(GoogleAdapter):
    api_base = "https://www.googleapis.com"
    spec = ConnectorSpec(
        key="google_calendar",
        name="Google Calendar",
        category="productivity",
        auth_type="oauth2",
        description="Consulta la agenda y crea eventos en Google Calendar.",
        description_en="Read calendars and create events in Google Calendar.",
        icon="google-calendar",
        oauth=google_oauth(
            ["https://www.googleapis.com/auth/calendar.readonly", "https://www.googleapis.com/auth/calendar.events"]
        ),
        capabilities=Capabilities(actions=["list_calendars", "list_events", "create_event"], demo=True),
        docs_url="https://developers.google.com/calendar/api/guides/overview",
    )

    def actions(self) -> list[ActionSpec]:
        return [
            ActionSpec(name="list_calendars", title="Listar calendarios", description="Calendarios de la cuenta."),
            ActionSpec(
                name="list_events",
                title="Listar eventos",
                description="Eventos entre dos fechas (por defecto, los próximos 7 días).",
                input_schema=obj_schema(
                    {
                        "calendar_id": {"type": "string", "default": "primary"},
                        "time_min": {"type": "string", "format": "date-time"},
                        "time_max": {"type": "string", "format": "date-time"},
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 250, "default": 50},
                    }
                ),
            ),
            ActionSpec(
                name="create_event",
                title="Crear evento",
                description="Crea un evento e invita a los asistentes.",
                input_schema=obj_schema(
                    {
                        "calendar_id": {"type": "string", "default": "primary"},
                        "summary": {"type": "string", "minLength": 1},
                        "description": {"type": "string"},
                        "location": {"type": "string"},
                        "start": {"type": "string", "format": "date-time"},
                        "end": {"type": "string", "format": "date-time"},
                        "time_zone": {"type": "string", "default": "Europe/Madrid"},
                        "attendees": {"type": "array", "items": {"type": "string", "format": "email"}, "default": []},
                        "send_updates": {"type": "boolean", "default": True},
                    },
                    ["summary", "start", "end"],
                ),
                side_effect=True,
            ),
        ]

    async def whoami(self, ctx: ConnectionContext) -> dict[str, Any]:
        async with self.session(ctx) as api:
            data = await api.get("/calendar/v3/users/me/calendarList", params={"minAccessRole": "owner"})
        primary = next((c for c in data.get("items", []) if c.get("primary")), None)
        return {"email": (primary or {}).get("id"), "calendars": len(data.get("items", []))}

    async def run_action(self, ctx: ConnectionContext, action: str, args: dict[str, Any]) -> Any:
        data = validate_args(self.action(action), args)
        async with self.session(ctx) as api:
            if action == "list_calendars":
                res = await api.get("/calendar/v3/users/me/calendarList")
                return [
                    {
                        "id": c.get("id"),
                        "name": c.get("summary"),
                        "primary": bool(c.get("primary")),
                        "time_zone": c.get("timeZone"),
                    }
                    for c in res.get("items", [])
                ]
            if action == "list_events":
                now = datetime.now(UTC)
                params = {
                    "timeMin": data.get("time_min") or to_rfc3339(now),
                    "timeMax": data.get("time_max") or to_rfc3339(now + timedelta(days=7)),
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "maxResults": int(data["limit"]),
                }
                if data.get("query"):
                    params["q"] = data["query"]
                res = await api.get(f"/calendar/v3/calendars/{data['calendar_id']}/events", params=params)
                return [_event_out(e) for e in res.get("items", [])]
            if action == "create_event":
                tz = data["time_zone"]
                body: dict[str, Any] = {
                    "summary": data["summary"],
                    "start": {"dateTime": data["start"], "timeZone": tz},
                    "end": {"dateTime": data["end"], "timeZone": tz},
                    "attendees": [{"email": a} for a in data.get("attendees", [])],
                }
                for key in ("description", "location"):
                    if data.get(key):
                        body[key] = data[key]
                res = await api.post(
                    f"/calendar/v3/calendars/{data['calendar_id']}/events",
                    params={"sendUpdates": "all" if data["send_updates"] else "none"},
                    json=body,
                )
                return _event_out(res)
        return await super().run_action(ctx, action, args)


def _event_out(evt: dict[str, Any]) -> dict[str, Any]:
    start = evt.get("start") or {}
    end = evt.get("end") or {}
    return {
        "id": evt.get("id"),
        "summary": evt.get("summary"),
        "description": evt.get("description"),
        "location": evt.get("location"),
        "start": start.get("dateTime") or start.get("date"),
        "end": end.get("dateTime") or end.get("date"),
        "attendees": [a.get("email") for a in evt.get("attendees", []) if a.get("email")],
        "status": evt.get("status"),
        "url": evt.get("htmlLink"),
    }
