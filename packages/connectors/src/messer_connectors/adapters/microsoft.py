"""Microsoft OneDrive, SharePoint and Outlook (mail + calendar) through Microsoft Graph."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

from messer_common.settings import get_settings

from ..base import (
    ActionSpec,
    Capabilities,
    ConfigError,
    ConnectionContext,
    ConnectorSpec,
    OAuthSpec,
    Resource,
    SyncFile,
    SyncOutcome,
    SyncRequest,
    SyncSink,
    obj_schema,
)
from ..demo import microsoft as demo_microsoft
from ..registry import register
from ..util import html_to_text, safe_filename, to_rfc3339, truncate, validate_args
from ._oauth import ApiSession, OAuthAdapter

GRAPH = "https://graph.microsoft.com"
ITEM_SELECT = "id,name,folder,file,size,createdDateTime,lastModifiedDateTime,webUrl,eTag,parentReference"
TEXT_MIMES = ("text/", "application/json", "application/xml")


def microsoft_oauth(scopes: list[str]) -> OAuthSpec:
    return OAuthSpec(
        provider="microsoft",
        authorize_url="https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
        token_url="https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        scopes=["offline_access", "User.Read", *scopes],
        client_id_setting="microsoft_client_id",
        client_secret_setting="microsoft_client_secret",
        pkce=True,
        extra_authorize_params={"prompt": "select_account", "response_mode": "query"},
    )


class GraphAdapter(OAuthAdapter):
    api_base = GRAPH
    demo_handler = staticmethod(demo_microsoft.handler)  # type: ignore[assignment]

    async def whoami(self, ctx: ConnectionContext) -> dict[str, Any]:
        async with self.session(ctx) as api:
            me = await api.get("/v1.0/me", params={"$select": "displayName,mail,userPrincipalName"})
        return {"email": me.get("mail") or me.get("userPrincipalName"), "name": me.get("displayName")}

    async def paged(
        self,
        api: ApiSession,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        limit: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        url: str | None = path
        first = True
        while url:
            data = await api.get(url, params=params if first else None, headers=dict(headers or {}))
            first = False
            items.extend(data.get("value", []))
            if limit is not None and len(items) >= limit:
                return items[:limit]
            url = data.get("@odata.nextLink")
        return items


# ============================================================================= drives (OneDrive + SharePoint)


def _drive_path(drive_id: str) -> str:
    return "/v1.0/me/drive" if drive_id == "me" else f"/v1.0/drives/{quote(drive_id, safe='')}"


def parse_folder(resource: str) -> tuple[str, str]:
    """``folder:<drive>:<item>`` → (drive, item); OneDrive also accepts ``folder:root`` / ``folder:<item>``."""
    value = resource.removeprefix("folder:")
    if ":" in value:
        drive, _, item = value.partition(":")
        return drive or "me", item or "root"
    return "me", value or "root"


def _children_path(drive_id: str, item_id: str) -> str:
    base = _drive_path(drive_id)
    return f"{base}/root/children" if item_id == "root" else f"{base}/items/{quote(item_id, safe='')}/children"


def _item_out(item: dict[str, Any], drive_id: str) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "drive_id": (item.get("parentReference") or {}).get("driveId") or drive_id,
        "name": item.get("name"),
        "is_folder": "folder" in item,
        "mime_type": (item.get("file") or {}).get("mimeType"),
        "size": item.get("size"),
        "modified_at": item.get("lastModifiedDateTime"),
        "url": item.get("webUrl"),
    }


class DriveAdapter(GraphAdapter):
    """Shared Graph drive logic: listing, search, content and folder sync."""

    def drive_actions(self, default_drive: str) -> list[ActionSpec]:
        return [
            ActionSpec(
                name="list_folder",
                title="Listar carpeta",
                description="Archivos y subcarpetas de una carpeta.",
                input_schema=obj_schema(
                    {
                        "drive_id": {"type": "string", "default": default_drive},
                        "item_id": {"type": "string", "default": "root"},
                    }
                ),
            ),
            ActionSpec(
                name="search_files",
                title="Buscar archivos",
                description="Busca archivos por nombre o contenido en la unidad.",
                input_schema=obj_schema(
                    {
                        "query": {"type": "string", "minLength": 1},
                        "drive_id": {"type": "string", "default": default_drive},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                    },
                    ["query"],
                ),
            ),
            ActionSpec(
                name="get_file",
                title="Leer archivo",
                description="Devuelve el texto de un archivo de texto, CSV o Markdown.",
                input_schema=obj_schema(
                    {
                        "item_id": {"type": "string", "minLength": 1},
                        "drive_id": {"type": "string", "default": default_drive},
                    },
                    ["item_id"],
                ),
            ),
        ]

    async def drive_action(self, ctx: ConnectionContext, action: str, data: dict[str, Any]) -> Any:
        drive = str(data.get("drive_id") or "me")
        async with self.session(ctx) as api:
            if action == "list_folder":
                items = await self.paged(
                    api, _children_path(drive, str(data["item_id"])), {"$select": ITEM_SELECT, "$top": 200}
                )
                return [_item_out(i, drive) for i in items]
            if action == "search_files":
                term = str(data["query"]).replace("'", "''")
                path = f"{_drive_path(drive)}/root/search(q='{quote(term, safe='')}')"
                items = await self.paged(api, path, {"$select": ITEM_SELECT}, limit=int(data["limit"]))
                return [_item_out(i, drive) for i in items]
            if action == "get_file":
                item_path = f"{_drive_path(drive)}/items/{quote(str(data['item_id']), safe='')}"
                meta = await api.get(item_path, params={"$select": ITEM_SELECT})
                out = _item_out(meta, drive)
                mime = out["mime_type"] or ""
                if mime.startswith(TEXT_MIMES) or str(out["name"]).lower().endswith((".md", ".txt", ".csv", ".json")):
                    res = await api.call("GET", f"{item_path}/content", raw=True)
                    out["content"] = truncate(res.content.decode("utf-8", "replace"), 50_000)
                else:
                    out["content"] = None
                    out["note"] = "Archivo binario: sincroniza la carpeta con una base de conocimiento para indexarlo."
                return out
        return None

    async def folder_resources(self, ctx: ConnectionContext, drive: str, item: str) -> list[Resource]:
        async with self.session(ctx) as api:
            children = await self.paged(api, _children_path(drive, item), {"$select": ITEM_SELECT, "$top": 200})
        return [
            Resource(
                id=f"folder:{drive}:{c['id']}",
                name=str(c.get("name")),
                kind="folder",
                has_children=bool((c.get("folder") or {}).get("childCount", 1)),
                parent=f"folder:{drive}:{item}",
            )
            for c in children
            if "folder" in c
        ]

    async def sync(self, ctx: ConnectionContext, request: SyncRequest, sink: SyncSink) -> SyncOutcome:
        if not request.resource.startswith("folder:"):
            raise ConfigError("El recurso debe ser una carpeta («folder:…»)")
        drive, root = parse_folder(request.resource)
        recursive = request.options.get("recursive", True) is not False
        since = request.cursor if request.mode == "incremental" else None
        max_bytes = get_settings().messer_connectors_max_file_mb * 1024 * 1024
        stats = {"files": 0, "skipped": 0, "too_large": 0, "folders": 0}
        newest = since
        queue: list[tuple[str, str]] = [(root, "")]
        async with self.session(ctx) as api:
            while queue:
                item_id, prefix = queue.pop(0)
                stats["folders"] += 1
                children = await self.paged(api, _children_path(drive, item_id), {"$select": ITEM_SELECT, "$top": 200})
                for child in children:
                    if "folder" in child:
                        if recursive:
                            queue.append((child["id"], f"{prefix}{child['name']}/"))
                        continue
                    if "file" not in child:
                        continue
                    modified = str(child.get("lastModifiedDateTime") or "")
                    if since and modified and modified <= since:
                        stats["skipped"] += 1
                        continue
                    if newest is None or modified > newest:
                        newest = modified
                    if int(child.get("size") or 0) > max_bytes:
                        stats["too_large"] += 1
                        continue
                    version = str(child.get("eTag") or modified)
                    if await sink.should_skip(child["id"], version):
                        stats["skipped"] += 1
                        continue
                    res = await api.call(
                        "GET", f"{_drive_path(drive)}/items/{quote(child['id'], safe='')}/content", raw=True
                    )
                    filename = safe_filename(str(child.get("name")))
                    await sink.file(
                        SyncFile(
                            external_id=child["id"],
                            filename=filename,
                            data=res.content,
                            mime=(child.get("file") or {}).get("mimeType"),
                            version=version,
                            modified_at=modified or None,
                            url=child.get("webUrl"),
                            path=f"{prefix}{filename}",
                        )
                    )
                    stats["files"] += 1
        return SyncOutcome(next_cursor=newest, stats=stats)


@register
class OneDriveAdapter(DriveAdapter):
    spec = ConnectorSpec(
        key="onedrive",
        name="Microsoft OneDrive",
        category="files",
        auth_type="oauth2",
        description="Archivos de OneDrive y sincronización de carpetas con el conocimiento.",
        description_en="OneDrive files and folder syncs into knowledge bases.",
        icon="onedrive",
        oauth=microsoft_oauth(["Files.Read.All"]),
        capabilities=Capabilities(
            actions=["list_folder", "search_files", "get_file"], sync=True, sync_resources=["folder"], demo=True
        ),
        docs_url="https://learn.microsoft.com/graph/onedrive-concept-overview",
    )

    def actions(self) -> list[ActionSpec]:
        return self.drive_actions("me")

    async def run_action(self, ctx: ConnectionContext, action: str, args: dict[str, Any]) -> Any:
        data = validate_args(self.action(action), args)
        return await self.drive_action(ctx, action, data)

    async def list_resources(self, ctx: ConnectionContext, parent: str | None = None) -> list[Resource]:
        if parent is None:
            root = Resource(id="folder:me:root", name="OneDrive", kind="folder", has_children=True)
            return [root, *await self.folder_resources(ctx, "me", "root")]
        drive, item = parse_folder(parent)
        return await self.folder_resources(ctx, drive, item)


@register
class SharePointAdapter(DriveAdapter):
    spec = ConnectorSpec(
        key="sharepoint",
        name="Microsoft SharePoint",
        category="files",
        auth_type="oauth2",
        description="Sitios y bibliotecas de documentos de SharePoint; sincroniza carpetas con el conocimiento.",
        description_en="SharePoint sites and document libraries; syncs folders into knowledge bases.",
        icon="sharepoint",
        oauth=microsoft_oauth(["Sites.Read.All", "Files.Read.All"]),
        capabilities=Capabilities(
            actions=["list_sites", "list_drives", "list_folder", "search_files", "get_file"],
            sync=True,
            sync_resources=["folder"],
            demo=True,
        ),
        docs_url="https://learn.microsoft.com/graph/api/resources/sharepoint",
    )

    def actions(self) -> list[ActionSpec]:
        drive_actions = []
        for spec in self.drive_actions(""):
            schema = dict(spec.input_schema)
            props = dict(schema.get("properties", {}))
            props["drive_id"] = {"type": "string", "minLength": 1}
            schema["properties"] = props
            schema["required"] = sorted({*schema.get("required", []), "drive_id"})
            drive_actions.append(spec.model_copy(update={"input_schema": schema}))
        return [
            ActionSpec(
                name="list_sites",
                title="Listar sitios",
                description="Sitios de SharePoint accesibles (filtrables por texto).",
                input_schema=obj_schema({"query": {"type": "string", "default": "*"}}),
            ),
            ActionSpec(
                name="list_drives",
                title="Listar bibliotecas",
                description="Bibliotecas de documentos de un sitio.",
                input_schema=obj_schema({"site_id": {"type": "string", "minLength": 1}}, ["site_id"]),
            ),
            *drive_actions,
        ]

    async def run_action(self, ctx: ConnectionContext, action: str, args: dict[str, Any]) -> Any:
        data = validate_args(self.action(action), args)
        if action == "list_sites":
            async with self.session(ctx) as api:
                sites = await self.paged(api, "/v1.0/sites", {"search": data["query"] or "*"})
            return [
                {
                    "id": s.get("id"),
                    "name": s.get("displayName") or s.get("name"),
                    "url": s.get("webUrl"),
                    "description": s.get("description"),
                }
                for s in sites
            ]
        if action == "list_drives":
            async with self.session(ctx) as api:
                drives = await self.paged(api, f"/v1.0/sites/{quote(str(data['site_id']), safe='')}/drives")
            return [{"id": d.get("id"), "name": d.get("name"), "url": d.get("webUrl")} for d in drives]
        return await self.drive_action(ctx, action, data)

    async def list_resources(self, ctx: ConnectionContext, parent: str | None = None) -> list[Resource]:
        async with self.session(ctx) as api:
            if parent is None:
                sites = await self.paged(api, "/v1.0/sites", {"search": "*"})
                return [
                    Resource(
                        id=f"site:{s['id']}",
                        name=str(s.get("displayName") or s.get("name")),
                        kind="site",
                        has_children=True,
                    )
                    for s in sites
                ]
            if parent.startswith("site:"):
                site = parent.removeprefix("site:")
                drives = await self.paged(api, f"/v1.0/sites/{quote(site, safe='')}/drives")
                return [
                    Resource(
                        id=f"folder:{d['id']}:root",
                        name=str(d.get("name")),
                        kind="library",
                        has_children=True,
                        parent=parent,
                    )
                    for d in drives
                ]
        drive, item = parse_folder(parent)
        return await self.folder_resources(ctx, drive, item)


# ============================================================================= Outlook


def _recipients(addresses: list[str]) -> list[dict[str, Any]]:
    return [{"emailAddress": {"address": a}} for a in addresses]


def _mail_out(msg: dict[str, Any], with_body: bool = False) -> dict[str, Any]:
    sender = (msg.get("from") or {}).get("emailAddress") or {}
    out: dict[str, Any] = {
        "id": msg.get("id"),
        "subject": msg.get("subject"),
        "from": f"{sender.get('name', '')} <{sender.get('address', '')}>".strip(),
        "from_email": sender.get("address"),
        "to": [((r.get("emailAddress") or {}).get("address")) for r in msg.get("toRecipients", [])],
        "date": msg.get("receivedDateTime"),
        "snippet": msg.get("bodyPreview"),
        "unread": not msg.get("isRead", True),
        "has_attachments": bool(msg.get("hasAttachments")),
        "url": msg.get("webLink"),
    }
    if with_body:
        body = msg.get("body") or {}
        content = str(body.get("content") or "")
        out["body"] = truncate(html_to_text(content) if body.get("contentType") == "html" else content, 50_000)
        out["cc"] = [((r.get("emailAddress") or {}).get("address")) for r in msg.get("ccRecipients", [])]
    return out


def _graph_event_out(evt: dict[str, Any]) -> dict[str, Any]:
    def when(value: dict[str, Any] | None) -> str | None:
        if not value:
            return None
        raw = str(value.get("dateTime") or "")
        if value.get("timeZone") == "UTC" and raw and not raw.endswith("Z"):
            raw = raw.split(".")[0] + "Z"
        return raw or None

    return {
        "id": evt.get("id"),
        "summary": evt.get("subject"),
        "location": (evt.get("location") or {}).get("displayName"),
        "start": when(evt.get("start")),
        "end": when(evt.get("end")),
        "attendees": [((a.get("emailAddress") or {}).get("address")) for a in evt.get("attendees", [])],
        "url": evt.get("webLink"),
    }


MAIL_SELECT = "id,subject,from,toRecipients,ccRecipients,receivedDateTime,bodyPreview,isRead,hasAttachments,webLink"


@register
class OutlookAdapter(GraphAdapter):
    spec = ConnectorSpec(
        key="outlook",
        name="Microsoft Outlook",
        category="communication",
        auth_type="oauth2",
        description="Correo y calendario de Outlook / Microsoft 365: buscar, leer, redactar, enviar y agendar.",
        description_en="Outlook / Microsoft 365 mail and calendar: search, read, draft, send and schedule.",
        icon="outlook",
        oauth=microsoft_oauth(["Mail.ReadWrite", "Mail.Send", "Calendars.ReadWrite"]),
        capabilities=Capabilities(
            actions=["search_messages", "get_message", "create_draft", "send_mail", "list_events", "create_event"],
            events=["new_email"],
            demo=True,
        ),
        docs_url="https://learn.microsoft.com/graph/outlook-mail-concept-overview",
    )

    def actions(self) -> list[ActionSpec]:
        emails = {"type": "array", "items": {"type": "string", "format": "email"}}
        compose = obj_schema(
            {
                "to": {**emails, "minItems": 1},
                "cc": emails,
                "subject": {"type": "string", "minLength": 1},
                "body": {"type": "string"},
                "html": {"type": "boolean", "default": False},
            },
            ["to", "subject", "body"],
        )
        return [
            ActionSpec(
                name="search_messages",
                title="Buscar correos",
                description="Busca correos por texto; sin texto, devuelve los últimos de la bandeja de entrada.",
                input_schema=obj_schema(
                    {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                    }
                ),
            ),
            ActionSpec(
                name="get_message",
                title="Leer correo",
                description="Remitente, destinatarios, asunto y cuerpo en texto.",
                input_schema=obj_schema({"message_id": {"type": "string", "minLength": 1}}, ["message_id"]),
            ),
            ActionSpec(
                name="create_draft",
                title="Crear borrador",
                description="Guarda un borrador.",
                input_schema=compose,
                side_effect=True,
            ),
            ActionSpec(
                name="send_mail",
                title="Enviar correo",
                description="Envía un correo.",
                input_schema=compose,
                side_effect=True,
            ),
            ActionSpec(
                name="list_events",
                title="Listar eventos",
                description="Eventos del calendario entre dos fechas (por defecto, próximos 7 días).",
                input_schema=obj_schema(
                    {
                        "start": {"type": "string", "format": "date-time"},
                        "end": {"type": "string", "format": "date-time"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
                    }
                ),
            ),
            ActionSpec(
                name="create_event",
                title="Crear evento",
                description="Crea un evento en el calendario y envía invitaciones.",
                input_schema=obj_schema(
                    {
                        "subject": {"type": "string", "minLength": 1},
                        "body": {"type": "string"},
                        "start": {"type": "string", "format": "date-time"},
                        "end": {"type": "string", "format": "date-time"},
                        "time_zone": {"type": "string", "default": "Europe/Madrid"},
                        "location": {"type": "string"},
                        "attendees": {**emails, "default": []},
                        "online_meeting": {"type": "boolean", "default": False},
                    },
                    ["subject", "start", "end"],
                ),
                side_effect=True,
            ),
        ]

    def _message_body(self, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "subject": data["subject"],
            "body": {"contentType": "HTML" if data.get("html") else "Text", "content": data.get("body", "")},
            "toRecipients": _recipients(data["to"]),
            "ccRecipients": _recipients(data.get("cc") or []),
        }

    async def run_action(self, ctx: ConnectionContext, action: str, args: dict[str, Any]) -> Any:
        data = validate_args(self.action(action), args)
        async with self.session(ctx) as api:
            if action == "search_messages":
                limit = int(data["limit"])
                if data.get("query"):
                    query = str(data["query"]).replace('"', "")
                    items = await self.paged(
                        api,
                        "/v1.0/me/messages",
                        {"$search": f'"{query}"', "$top": limit, "$select": MAIL_SELECT},
                        limit=limit,
                    )
                else:
                    items = await self.paged(
                        api,
                        "/v1.0/me/mailFolders/inbox/messages",
                        {"$top": limit, "$orderby": "receivedDateTime desc", "$select": MAIL_SELECT},
                        limit=limit,
                    )
                return [_mail_out(m) for m in items]
            if action == "get_message":
                msg = await api.get(
                    f"/v1.0/me/messages/{quote(str(data['message_id']), safe='')}",
                    params={"$select": f"{MAIL_SELECT},body"},
                    headers={"Prefer": 'outlook.body-content-type="text"'},
                )
                return _mail_out(msg, with_body=True)
            if action == "create_draft":
                draft = await api.post("/v1.0/me/messages", json=self._message_body(data))
                return {"message_id": draft.get("id"), "status": "draft", "url": draft.get("webLink")}
            if action == "send_mail":
                await api.post("/v1.0/me/sendMail", json={"message": self._message_body(data), "saveToSentItems": True})
                return {"status": "sent", "to": data["to"]}
            if action == "list_events":
                now = datetime.now(UTC)
                items = await self.paged(
                    api,
                    "/v1.0/me/calendarView",
                    {
                        "startDateTime": data.get("start") or to_rfc3339(now),
                        "endDateTime": data.get("end") or to_rfc3339(now + timedelta(days=7)),
                        "$orderby": "start/dateTime",
                        "$top": int(data["limit"]),
                    },
                    limit=int(data["limit"]),
                    headers={"Prefer": 'outlook.timezone="UTC"'},
                )
                return [_graph_event_out(e) for e in items]
            if action == "create_event":
                tz = data["time_zone"]
                body: dict[str, Any] = {
                    "subject": data["subject"],
                    "body": {"contentType": "Text", "content": data.get("body", "")},
                    "start": {"dateTime": data["start"], "timeZone": tz},
                    "end": {"dateTime": data["end"], "timeZone": tz},
                    "attendees": [
                        {"emailAddress": {"address": a}, "type": "required"} for a in data.get("attendees", [])
                    ],
                }
                if data.get("location"):
                    body["location"] = {"displayName": data["location"]}
                if data.get("online_meeting"):
                    body["isOnlineMeeting"] = True
                    body["onlineMeetingProvider"] = "teamsForBusiness"
                return _graph_event_out(await api.post("/v1.0/me/events", json=body))
        return await super().run_action(ctx, action, args)

    async def poll_events(
        self, ctx: ConnectionContext, event: str, cursor: str | None
    ) -> tuple[list[dict[str, Any]], str | None]:
        self._check_event(event)
        if cursor is None:
            return [], to_rfc3339(datetime.now(UTC))
        async with self.session(ctx) as api:
            items = await self.paged(
                api,
                "/v1.0/me/mailFolders/inbox/messages",
                {
                    "$filter": f"receivedDateTime gt {cursor}",
                    "$orderby": "receivedDateTime asc",
                    "$top": 50,
                    "$select": MAIL_SELECT,
                },
                limit=200,
            )
        events = [
            {"id": m["id"], "event": "new_email", "occurred_at": m.get("receivedDateTime"), "data": _mail_out(m)}
            for m in items
        ]
        newest = max((str(m.get("receivedDateTime")) for m in items), default=cursor)
        return events, newest
