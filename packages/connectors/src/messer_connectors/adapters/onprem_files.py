"""Files on the customer's network, read by an on-prem connector agent from its configured local paths."""

from __future__ import annotations

import base64
from typing import Any

from messer_common.settings import get_settings

from ..agent_rpc import call
from ..base import (
    ActionSpec,
    Capabilities,
    ConfigError,
    ConfigField,
    ConnectionContext,
    ConnectorAdapter,
    ConnectorSpec,
    Resource,
    SyncFile,
    SyncOutcome,
    SyncRequest,
    SyncSink,
    TestResult,
    obj_schema,
)
from ..registry import register
from ..util import truncate, validate_args

# Files travel base64-encoded over the agent socket; keep single messages reasonable.
MAX_AGENT_FILE_MB = 25
TEXT_EXTENSIONS = (".txt", ".md", ".csv", ".json", ".xml", ".html", ".htm", ".log", ".yaml", ".yml")


@register
class OnPremFilesAdapter(ConnectorAdapter):
    spec = ConnectorSpec(
        key="onprem_files",
        name="Archivos on-premise",
        category="files",
        auth_type="agent",
        description="Copia archivos de carpetas de tu red al conocimiento mediante el agente on-premise.",
        description_en="Copy files from folders on your network into knowledge through the on-prem agent.",
        icon="server",
        capabilities=Capabilities(actions=["list_files", "read_file"], sync=True, sync_resources=["path"], agent=True),
        config_fields=[ConfigField(key="root", kind="text", required=True, placeholder="/srv/documentos")],
    )

    def actions(self) -> list[ActionSpec]:
        return [
            ActionSpec(
                name="list_files",
                title="Listar archivos",
                description="Archivos y carpetas de una ruta permitida en el agente.",
                input_schema=obj_schema({"path": {"type": "string", "default": ""}}),
            ),
            ActionSpec(
                name="read_file",
                title="Leer archivo de texto",
                description="Contenido de un archivo de texto (CSV, Markdown, TXT…).",
                input_schema=obj_schema({"path": {"type": "string", "minLength": 1}}, ["path"]),
            ),
        ]

    def validate_config(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        if not config.get("root"):
            raise ConfigError("Indica la carpeta raíz configurada en el agente", details={"field": "root"})

    def _agent(self, ctx: ConnectionContext) -> Any:
        if ctx.agent_id is None:
            raise ConfigError("Esta conexión necesita un agente on-premise")
        return ctx.agent_id

    def _path(self, ctx: ConnectionContext, sub: str) -> str:
        root = str(ctx.config.get("root") or "").rstrip("/")
        sub = sub.strip()
        if not sub:
            return root
        if sub.startswith(root):
            return sub
        return f"{root}/{sub.lstrip('/')}"

    async def test(self, ctx: ConnectionContext) -> TestResult:
        info = await call(self._agent(ctx), "ping", {})
        listing = await call(self._agent(ctx), "files.list", {"path": self._path(ctx, ""), "recursive": False})
        return TestResult(
            ok=True,
            message=f"Agente conectado ({info.get('hostname', '')}); {len(listing.get('entries', []))} elementos en la raíz",
            details={"agent": info},
        )

    async def run_action(self, ctx: ConnectionContext, action: str, args: dict[str, Any]) -> Any:
        data = validate_args(self.action(action), args)
        agent = self._agent(ctx)
        if action == "list_files":
            res = await call(agent, "files.list", {"path": self._path(ctx, str(data["path"])), "recursive": False})
            return res.get("entries", [])
        if action == "read_file":
            res = await call(
                agent, "files.read", {"path": self._path(ctx, str(data["path"])), "max_bytes": 2 * 1024 * 1024}
            )
            raw = base64.b64decode(res.get("data_b64") or "")
            return {
                "path": res.get("path"),
                "size": res.get("size"),
                "content": truncate(raw.decode("utf-8", "replace"), 50_000),
            }
        return await super().run_action(ctx, action, args)

    async def list_resources(self, ctx: ConnectionContext, parent: str | None = None) -> list[Resource]:
        base = parent.removeprefix("path:") if parent else self._path(ctx, "")
        res = await call(self._agent(ctx), "files.list", {"path": base, "recursive": False})
        out: list[Resource] = []
        if parent is None:
            out.append(Resource(id=f"path:{base}", name=base, kind="folder", has_children=True))
        for entry in res.get("entries", []):
            if entry.get("is_dir"):
                out.append(
                    Resource(
                        id=f"path:{entry['path']}",
                        name=str(entry["name"]),
                        kind="folder",
                        has_children=True,
                        parent=f"path:{base}",
                    )
                )
        return out

    async def sync(self, ctx: ConnectionContext, request: SyncRequest, sink: SyncSink) -> SyncOutcome:
        agent = self._agent(ctx)
        base = request.resource.removeprefix("path:") or self._path(ctx, "")
        limit_mb = min(MAX_AGENT_FILE_MB, get_settings().messer_connectors_max_file_mb)
        max_bytes = limit_mb * 1024 * 1024
        listing = await call(
            agent,
            "files.list",
            {"path": base, "recursive": request.options.get("recursive", True) is not False},
            timeout_s=120,
        )
        since = request.cursor if request.mode == "incremental" else None
        extensions = [str(e).lower() for e in request.options.get("extensions") or []]
        stats = {"files": 0, "skipped": 0, "too_large": 0}
        newest = since
        for entry in listing.get("entries", []):
            if entry.get("is_dir"):
                continue
            name = str(entry.get("name") or "")
            if extensions and not name.lower().endswith(tuple(extensions)):
                continue
            modified = str(entry.get("modified_at") or "")
            if since and modified and modified <= since:
                stats["skipped"] += 1
                continue
            if newest is None or modified > newest:
                newest = modified
            if int(entry.get("size") or 0) > max_bytes:
                stats["too_large"] += 1
                continue
            version = f"{modified}:{entry.get('size')}"
            if await sink.should_skip(str(entry["path"]), version):
                stats["skipped"] += 1
                continue
            res = await call(agent, "files.read", {"path": entry["path"], "max_bytes": max_bytes}, timeout_s=180)
            await sink.file(
                SyncFile(
                    external_id=str(entry["path"]),
                    filename=name,
                    data=base64.b64decode(res.get("data_b64") or ""),
                    mime=res.get("mime"),
                    version=version,
                    modified_at=modified or None,
                    path=str(entry["path"]),
                )
            )
            stats["files"] += 1
        return SyncOutcome(next_cursor=newest, stats=stats)
