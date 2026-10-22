"""Notion: search, read pages as Markdown and sync pages or databases into knowledge bases."""

from __future__ import annotations

from typing import Any

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
from ..demo import saas as demo_saas
from ..registry import register
from ..util import safe_filename, truncate, validate_args
from ._oauth import ApiSession, OAuthAdapter

NOTION_VERSION = "2022-06-28"
MAX_DEPTH = 3
MAX_PAGES = 2000


def rich_text(items: list[dict[str, Any]] | None) -> str:
    out = []
    for item in items or []:
        text = item.get("plain_text") or (item.get("text") or {}).get("content") or ""
        href = item.get("href")
        out.append(f"[{text}]({href})" if href and text else text)
    return "".join(out)


def page_title(page: dict[str, Any]) -> str:
    if page.get("object") == "database":
        return rich_text(page.get("title")) or "Base de datos sin título"
    for prop in (page.get("properties") or {}).values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            return rich_text(prop.get("title")) or "Sin título"
    return "Sin título"


def property_text(prop: dict[str, Any]) -> str:
    kind = prop.get("type")
    value = prop.get(kind) if kind else None
    if kind in ("title", "rich_text"):
        return rich_text(value)
    if kind in ("select", "status"):
        return (value or {}).get("name", "")
    if kind == "multi_select":
        return ", ".join(v.get("name", "") for v in value or [])
    if kind in ("number", "checkbox", "url", "email", "phone_number", "created_time", "last_edited_time"):
        return "" if value is None else str(value)
    if kind == "date":
        return (value or {}).get("start", "") or ""
    if kind == "people":
        return ", ".join(p.get("name", "") for p in value or [])
    if kind == "formula":
        inner = value or {}
        return str(inner.get(inner.get("type", ""), ""))
    return ""


def blocks_to_markdown(blocks: list[dict[str, Any]], depth: int = 0) -> list[str]:
    lines: list[str] = []
    indent = "  " * depth
    number = 0
    for block in blocks:
        kind = block.get("type", "")
        data = block.get(kind) or {}
        text = rich_text(data.get("rich_text"))
        number = number + 1 if kind == "numbered_list_item" else 0
        if kind == "paragraph":
            lines.append(f"{indent}{text}" if text else "")
        elif kind in ("heading_1", "heading_2", "heading_3"):
            lines.append(f"{'#' * int(kind[-1])} {text}")
        elif kind == "bulleted_list_item":
            lines.append(f"{indent}- {text}")
        elif kind == "numbered_list_item":
            lines.append(f"{indent}{number}. {text}")
        elif kind == "to_do":
            lines.append(f"{indent}- [{'x' if data.get('checked') else ' '}] {text}")
        elif kind == "quote":
            lines.append(f"{indent}> {text}")
        elif kind == "callout":
            emoji = (data.get("icon") or {}).get("emoji", "")
            lines.append(f"{indent}> {emoji} {text}".rstrip())
        elif kind == "toggle":
            lines.append(f"{indent}- {text}")
        elif kind == "code":
            lines.extend([f"```{data.get('language', '')}", text, "```"])
        elif kind == "divider":
            lines.append("---")
        elif kind == "child_page":
            lines.append(f"{indent}- Subpágina: {data.get('title', '')}")
        elif kind == "child_database":
            lines.append(f"{indent}- Base de datos: {data.get('title', '')}")
        elif kind == "table_row":
            cells = [rich_text(c) for c in data.get("cells", [])]
            lines.append("| " + " | ".join(cells) + " |")
        elif kind in ("image", "file", "pdf", "video"):
            src = data.get(data.get("type", ""), {}) if isinstance(data, dict) else {}
            caption = rich_text(data.get("caption")) or kind
            lines.append(f"{indent}[{caption}]({(src or {}).get('url', '')})")
        elif kind in ("bookmark", "embed", "link_preview"):
            lines.append(f"{indent}{data.get('url', '')}")
        elif kind == "equation":
            lines.append(f"$$ {data.get('expression', '')} $$")
        children = block.get("_children")
        if children:
            child_lines = blocks_to_markdown(children, depth + (0 if kind == "table" else 1))
            if kind == "table" and child_lines:
                header = child_lines[0]
                cols = header.count("|") - 1
                child_lines.insert(1, "|" + " --- |" * max(cols, 1))
            lines.extend(child_lines)
    return lines


@register
class NotionAdapter(OAuthAdapter):
    api_base = "https://api.notion.com"
    demo_handler = staticmethod(demo_saas.notion_handler)  # type: ignore[assignment]
    spec = ConnectorSpec(
        key="notion",
        name="Notion",
        category="productivity",
        auth_type="oauth2",
        description="Busca y lee páginas de Notion y sincroniza páginas o bases de datos con el conocimiento.",
        description_en="Search and read Notion pages and sync pages or databases into knowledge bases.",
        icon="notion",
        oauth=OAuthSpec(
            provider="notion",
            authorize_url="https://api.notion.com/v1/oauth/authorize",
            token_url="https://api.notion.com/v1/oauth/token",
            scopes=[],
            client_id_setting="notion_client_id",
            client_secret_setting="notion_client_secret",
            extra_authorize_params={"owner": "user"},
            token_auth="basic",
            token_body="json",
        ),
        capabilities=Capabilities(
            actions=["search", "get_page", "query_database"], sync=True, sync_resources=["page", "database"], demo=True
        ),
        docs_url="https://developers.notion.com/reference/intro",
    )

    def extra_headers(self, ctx: ConnectionContext) -> dict[str, str]:
        return {"Notion-Version": NOTION_VERSION, "Content-Type": "application/json"}

    def actions(self) -> list[ActionSpec]:
        return [
            ActionSpec(
                name="search",
                title="Buscar",
                description="Busca páginas y bases de datos compartidas con la integración.",
                input_schema=obj_schema(
                    {
                        "query": {"type": "string", "default": ""},
                        "type": {"type": "string", "enum": ["page", "database", "any"], "default": "any"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                    }
                ),
            ),
            ActionSpec(
                name="get_page",
                title="Leer página",
                description="Devuelve el contenido de una página en Markdown.",
                input_schema=obj_schema({"page_id": {"type": "string", "minLength": 1}}, ["page_id"]),
            ),
            ActionSpec(
                name="query_database",
                title="Consultar base de datos",
                description="Filas de una base de datos de Notion con sus propiedades.",
                input_schema=obj_schema(
                    {
                        "database_id": {"type": "string", "minLength": 1},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
                    },
                    ["database_id"],
                ),
            ),
        ]

    async def whoami(self, ctx: ConnectionContext) -> dict[str, Any]:
        async with self.session(ctx) as api:
            me = await api.get("/v1/users/me")
        return {"name": me.get("name"), "account": (me.get("bot") or {}).get("workspace_name")}

    async def _search(self, api: ApiSession, query: str, kind: str | None, limit: int) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        cursor: str | None = None
        while len(results) < limit:
            body: dict[str, Any] = {
                "query": query,
                "page_size": min(100, limit - len(results)),
                "sort": {"direction": "descending", "timestamp": "last_edited_time"},
            }
            if kind in ("page", "database"):
                body["filter"] = {"property": "object", "value": kind}
            if cursor:
                body["start_cursor"] = cursor
            res = await api.post("/v1/search", json=body)
            results.extend(res.get("results", []))
            cursor = res.get("next_cursor")
            if not res.get("has_more") or not cursor:
                break
        return results[:limit]

    async def _children(self, api: ApiSession, block_id: str, depth: int = 0) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            res = await api.get(f"/v1/blocks/{block_id}/children", params=params)
            blocks.extend(res.get("results", []))
            cursor = res.get("next_cursor")
            if not res.get("has_more") or not cursor:
                break
        if depth < MAX_DEPTH:
            for block in blocks:
                if block.get("has_children") and block.get("type") not in ("child_page", "child_database"):
                    block["_children"] = await self._children(api, block["id"], depth + 1)
        return blocks

    async def _page_markdown(self, api: ApiSession, page: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        title = page_title(page)
        blocks = await self._children(api, page["id"])
        lines = [f"# {title}", ""]
        props = [
            (name, property_text(prop))
            for name, prop in (page.get("properties") or {}).items()
            if isinstance(prop, dict) and prop.get("type") != "title"
        ]
        props = [(n, v) for n, v in props if v]
        if props:
            lines.extend([f"- **{n}:** {v}" for n, v in props])
            lines.append("")
        lines.extend(blocks_to_markdown(blocks))
        return "\n".join(lines).strip() + "\n", blocks

    async def run_action(self, ctx: ConnectionContext, action: str, args: dict[str, Any]) -> Any:
        data = validate_args(self.action(action), args)
        async with self.session(ctx) as api:
            if action == "search":
                kind = None if data["type"] == "any" else data["type"]
                return [_summary(r) for r in await self._search(api, data["query"], kind, int(data["limit"]))]
            if action == "get_page":
                page = await api.get(f"/v1/pages/{data['page_id']}")
                markdown, _ = await self._page_markdown(api, page)
                return {**_summary(page), "content": truncate(markdown, 50_000)}
            if action == "query_database":
                rows = await self._database_rows(api, str(data["database_id"]), int(data["limit"]))
                return [
                    {
                        **_summary(r),
                        "properties": {
                            n: property_text(p) for n, p in (r.get("properties") or {}).items() if isinstance(p, dict)
                        },
                    }
                    for r in rows
                ]
        return await super().run_action(ctx, action, args)

    async def _database_rows(self, api: ApiSession, database_id: str, limit: int) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        cursor: str | None = None
        while len(rows) < limit:
            body: dict[str, Any] = {"page_size": min(100, limit - len(rows))}
            if cursor:
                body["start_cursor"] = cursor
            res = await api.post(f"/v1/databases/{database_id}/query", json=body)
            rows.extend(res.get("results", []))
            cursor = res.get("next_cursor")
            if not res.get("has_more") or not cursor:
                break
        return rows[:limit]

    async def list_resources(self, ctx: ConnectionContext, parent: str | None = None) -> list[Resource]:
        if parent is not None:
            return []
        async with self.session(ctx) as api:
            items = await self._search(api, "", None, 100)
        out = [Resource(id="all", name="Todo lo compartido con Messer", kind="workspace")]
        for item in items:
            kind = "database" if item.get("object") == "database" else "page"
            top = (item.get("parent") or {}).get("type") == "workspace"
            if kind == "page" and (item.get("parent") or {}).get("type") == "database_id":
                continue
            out.append(
                Resource(
                    id=f"{kind}:{item['id']}",
                    name=page_title(item),
                    kind=kind,
                    meta={"top_level": top, "url": item.get("url")},
                )
            )
        return out

    async def sync(self, ctx: ConnectionContext, request: SyncRequest, sink: SyncSink) -> SyncOutcome:
        resource = request.resource
        since = request.cursor if request.mode == "incremental" else None
        stats = {"files": 0, "skipped": 0, "pages": 0}
        newest = since
        async with self.session(ctx) as api:
            if resource == "all":
                pages = [p for p in await self._search(api, "", "page", MAX_PAGES)]
            elif resource.startswith("database:"):
                pages = await self._database_rows(api, resource.removeprefix("database:"), MAX_PAGES)
            elif resource.startswith("page:"):
                pages = await self._page_tree(api, resource.removeprefix("page:"))
            else:
                raise ConfigError("Recurso no válido: usa «all», «page:<id>» o «database:<id>»")
            for page in pages:
                stats["pages"] += 1
                edited = str(page.get("last_edited_time") or "")
                if since and edited and edited <= since:
                    stats["skipped"] += 1
                    continue
                if newest is None or edited > newest:
                    newest = edited
                if await sink.should_skip(page["id"], edited):
                    stats["skipped"] += 1
                    continue
                markdown, _ = await self._page_markdown(api, page)
                filename = safe_filename(page_title(page)) + ".md"
                await sink.file(
                    SyncFile(
                        external_id=page["id"],
                        filename=filename,
                        data=markdown.encode(),
                        mime="text/markdown",
                        version=edited,
                        modified_at=edited or None,
                        url=page.get("url"),
                        path=filename,
                    )
                )
                stats["files"] += 1
        return SyncOutcome(next_cursor=newest, stats=stats)

    async def _page_tree(self, api: ApiSession, root_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        queue = [root_id]
        seen: set[str] = set()
        while queue and len(out) < MAX_PAGES:
            pid = queue.pop(0)
            if pid in seen:
                continue
            seen.add(pid)
            page = await api.get(f"/v1/pages/{pid}")
            out.append(page)
            blocks = await self._children(api, pid, MAX_DEPTH)  # only direct children: child pages
            queue.extend(b["id"] for b in blocks if b.get("type") == "child_page")
        return out


def _summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "type": item.get("object"),
        "title": page_title(item),
        "url": item.get("url"),
        "last_edited_at": item.get("last_edited_time"),
    }
