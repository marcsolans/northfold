"""Self-contained project export (spec 7.11): a .zip that starts with ``docker compose up``.

Layout (inside ``<slug>/``)::

    README.md, docker-compose.yml, Dockerfile, .env.example, secrets.env.example, .dockerignore
    messer-export.json                manifest (project, commit, members and ports, knowledge bases)
    requirements.txt, constraints.txt extra project dependencies; versions pinned from this Messer build
    vendor/messer_core-*.whl          the engine, built once per engine source fingerprint and cached
    project/                          the project repository at the requested ref
    .messer/entrypoints/entry_*.py    one loader per workforce member (``python -m messer.server``)
    data/knowledge/…                  linked knowledge bases: chunks JSONL, tables as CSV + schema JSON

``docker compose up`` starts a ``platform`` container (``python -m messer.platform.standalone``: tracing, model
proxy, knowledge search, read-only SQL, email, files) and one container per member on ports 8001, 8002, …

Knowledge data is read with the *agent* role (``messer_common.knowledge.sql.run_readonly``), so knowledge-base
policies apply exactly as they do for the project's agents in Messer. Project secrets are never exported.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import tarfile
import tempfile
import tomllib
import uuid
import zipfile
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common.db import Principal, system_session
from messer_common.db.models import KbTable, KnowledgeBase, Project, Secret
from messer_common.knowledge.errors import KnowledgeError
from messer_common.knowledge.sql import run_readonly
from messer_common.knowledge.sqlcheck import quote_ident
from messer_common.logging import get_logger
from messer_common.projects_repo import ProjectRepo, RepoError
from messer_common.settings import REPO_ROOT, get_settings

from ..errors import ApiError, NotFound

log = get_logger("messer.api.export")

FORMAT = "messer-export/1"
FIRST_MEMBER_PORT = 8001
PLATFORM_PORT = 8000
CHUNK_PAGE = 2000
ROW_PAGE = 10_000
MAX_ROWS_PER_TABLE = 1_000_000
MAX_CHUNKS_PER_KB = 1_000_000
_UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_REF_RE = re.compile(r"^[A-Za-z0-9._/~^@{}-]{1,200}$")
_MEMBER_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_FILE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.py$")
_ATTR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TABLE_FILE_RE = re.compile(r"[^A-Za-z0-9_.-]+")


class ExportError(ApiError):
    status_code = 503
    code = "export_unavailable"


@dataclass(slots=True)
class Member:
    name: str
    kind: str
    module: str
    attr: str
    port: int
    service: str


@dataclass(slots=True)
class ExportResult:
    path: Path
    filename: str
    commit: str
    size: int
    manifest: dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------------------------------------ engine wheel

_wheel_lock = asyncio.Lock()


def _engine_root() -> Path:
    return REPO_ROOT / "packages" / "messer-core"


def _engine_version(root: Path) -> str:
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _fingerprint(root: Path) -> str:
    """Version plus (path, size, mtime) of every engine source file: a new build only when the engine changes."""
    digest = hashlib.sha256(_engine_version(root).encode())
    digest.update((root / "pyproject.toml").read_bytes())
    for path in sorted((root / "python" / "messer").rglob("*")):
        if "__pycache__" in path.parts or not path.is_file() or path.suffix == ".pyc":
            continue
        stat = path.stat()
        digest.update(f"{path.relative_to(root)}:{stat.st_size}:{stat.st_mtime_ns}\n".encode())
    return digest.hexdigest()[:20]


def _uv_binary() -> str | None:
    configured = os.environ.get("MESSER_UV_BIN")
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which("uv")
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / "uv"
    return str(fallback) if fallback.is_file() else None


def _override_wheel(value: str) -> Path:
    path = Path(value)
    if not path.is_file():
        raise ExportError("MESSER_ENGINE_WHEEL no apunta a un archivo .whl existente")
    return path


async def engine_wheel() -> Path:
    """The engine wheel bundled in exports: ``MESSER_ENGINE_WHEEL`` (prebuilt, e.g. in the API image) or built
    from ``packages/messer-core`` with ``uv build --wheel`` into the runtime cache, once per engine fingerprint."""
    override = os.environ.get("MESSER_ENGINE_WHEEL")
    if override:
        return _override_wheel(override)
    root = _engine_root()
    if not (root / "pyproject.toml").is_file():
        raise ExportError("No se encuentra el motor (packages/messer-core) para generar la exportación")
    fingerprint = await asyncio.to_thread(_fingerprint, root)
    target = get_settings().runtime_cache_dir / "engine-wheels" / fingerprint
    existing = sorted(target.glob("messer_core-*.whl")) if target.is_dir() else []
    if existing:
        return existing[0]
    async with _wheel_lock:
        existing = sorted(target.glob("messer_core-*.whl")) if target.is_dir() else []
        if existing:
            return existing[0]
        uv = _uv_binary()
        if uv is None:
            raise ExportError("No se puede construir el motor: uv no está instalado (o define MESSER_ENGINE_WHEEL)")
        tmp = target.parent / f"{fingerprint}.tmp-{uuid.uuid4().hex[:8]}"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        proc = await asyncio.create_subprocess_exec(
            uv,
            "build",
            "--wheel",
            "--quiet",
            "--out-dir",
            str(tmp),
            str(root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _out, err = await asyncio.wait_for(proc.communicate(), timeout=600)
        except TimeoutError as exc:
            proc.kill()
            shutil.rmtree(tmp, ignore_errors=True)
            raise ExportError("La construcción del motor ha superado el tiempo máximo") from exc
        built = sorted(tmp.glob("messer_core-*.whl"))
        if proc.returncode != 0 or not built:
            shutil.rmtree(tmp, ignore_errors=True)
            log.error("export.wheel_build_failed", stderr=err.decode(errors="replace")[-2000:])
            raise ExportError("No se ha podido construir el motor para la exportación")
        try:
            tmp.rename(target)
        except OSError:  # another process finished first
            shutil.rmtree(tmp, ignore_errors=True)
        log.info("export.wheel_built", fingerprint=fingerprint)
        return sorted(target.glob("messer_core-*.whl"))[0]


def pinned_constraints() -> list[str]:
    """``name==version`` for the engine's runtime dependencies (``server``/``evals`` extras), resolved
    transitively from the packages installed in this Messer build, so exports install the tested versions."""
    try:
        from importlib import metadata

        from packaging.requirements import InvalidRequirement, Requirement
        from packaging.utils import canonicalize_name
    except ImportError:
        return []
    pins: dict[str, str] = {}
    queue: list[tuple[str, set[str]]] = [("messer-core", {"server", "evals"})]
    visited: set[tuple[str, frozenset[str]]] = set()
    while queue:
        name, extras = queue.pop()
        key = (canonicalize_name(name), frozenset(extras))
        if key in visited:
            continue
        visited.add(key)
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        for raw in dist.requires or []:
            try:
                req = Requirement(raw)
            except InvalidRequirement:
                continue
            if req.marker is not None and not any(req.marker.evaluate({"extra": e}) for e in {"", *extras}):
                continue
            dep = canonicalize_name(req.name)
            if dep == "messer-core":
                continue
            try:
                pins.setdefault(dep, metadata.version(req.name))
            except metadata.PackageNotFoundError:
                continue
            queue.append((req.name, set(req.extras)))
    for extra in ("python-multipart",):  # used by the standalone platform's file uploads
        try:
            pins.setdefault(canonicalize_name(extra), metadata.version(extra))
        except metadata.PackageNotFoundError:
            pass
    return [f"{name}=={version}" for name, version in sorted(pins.items())]


# --------------------------------------------------------------------------------------------- project


def _safe_extract(data: bytes, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        members = [m for m in tar.getmembers() if m.isfile() or m.isdir()]  # no links or devices
        tar.extractall(target, members=members, filter="data")


def discover_members(project_dir: Path) -> list[Member]:
    members: list[Member] = []
    base = project_dir / "workforce"
    used_services = {"platform"}
    for manifest_path in sorted(base.glob("*/messer.yaml")) if base.is_dir() else []:
        name = manifest_path.parent.name
        if not _MEMBER_RE.match(name):
            continue
        try:
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            manifest = {}
        manifest = manifest if isinstance(manifest, dict) else {}
        kind = str(manifest.get("_type") or "agent")
        default = "agent.py::agent" if kind == "agent" else "workflow.py::workflow"
        file_part, _, attr = str(manifest.get("fqn") or default).partition("::")
        if not _FILE_RE.match(file_part) or not _ATTR_RE.match(attr or ""):
            file_part, _, attr = default.partition("::")
        if not (manifest_path.parent / file_part).is_file():
            continue
        service = name.replace("_", "-")
        while service in used_services:
            service = f"{service}-member"
        used_services.add(service)
        members.append(
            Member(
                name=name,
                kind=kind,
                module=f"workforce.{name}.{file_part[:-3]}",
                attr=attr,
                port=FIRST_MEMBER_PORT + len(members),
                service=service,
            )
        )
    return members


def entrypoint_source(member: Member) -> str:
    return (
        "# Generated by Messer export: loads the member as a package (so relative imports work)\n"
        "# for `python -m messer.server --import_spec <this file>::runnable`.\n"
        "import importlib\nimport os\nimport sys\nfrom pathlib import Path\n\n"
        'PROJECT_DIR = Path(os.environ.get("MESSER_PROJECT_DIR") or Path(__file__).resolve().parents[2] / "project")\n'
        "if str(PROJECT_DIR) not in sys.path:\n    sys.path.insert(0, str(PROJECT_DIR))\n\n"
        f"runnable = getattr(importlib.import_module({member.module!r}), {member.attr!r})\n"
    )


def _project_requirements(project_dir: Path) -> tuple[list[str], list[str]]:
    """Extra dependencies declared in the project's ``pyproject.toml`` (the engine itself comes from vendor/)."""
    path = project_dir / "pyproject.toml"
    if not path.is_file():
        return [], []
    try:
        from packaging.requirements import InvalidRequirement, Requirement
        from packaging.utils import canonicalize_name
    except ImportError:
        return [], []
    warnings: list[str] = []
    try:
        deps = tomllib.loads(path.read_text(encoding="utf-8")).get("project", {}).get("dependencies", []) or []
    except tomllib.TOMLDecodeError:
        return [], ["pyproject.toml no es válido: se ignoran sus dependencias"]
    out: list[str] = []
    for raw in deps:
        try:
            req = Requirement(str(raw))
        except InvalidRequirement:
            warnings.append(f"Dependencia ignorada (formato no válido): {raw}")
            continue
        if canonicalize_name(req.name) == "messer-core" or req.url:
            continue
        out.append(str(req))
    return out, warnings


# ------------------------------------------------------------------------------------------- knowledge


async def linked_knowledge_bases(project: Project, project_dir: Path) -> list[KnowledgeBase]:
    """Knowledge bases of the project (``project_id``) or referenced by its code/config at the exported ref."""
    referenced: set[str] = set()
    candidates = [project_dir / "knowledge.yaml"]
    workforce = project_dir / "workforce"
    if workforce.is_dir():
        candidates += [p for p in workforce.rglob("*") if p.suffix in (".py", ".yaml", ".yml", ".json") and p.is_file()]
    for path in candidates:
        if path.is_file() and path.stat().st_size < 2_000_000:
            referenced.update(m.lower() for m in _UUID_RE.findall(path.read_text(encoding="utf-8", errors="ignore")))
    async with system_session() as s:
        rows = (await s.execute(select(KnowledgeBase).where(KnowledgeBase.org_id == project.org_id))).scalars().all()
        kbs = [kb for kb in rows if kb.project_id == project.id or str(kb.id) in referenced]
        for kb in kbs:
            s.expunge(kb)
    return sorted(kbs, key=lambda kb: kb.name.lower())


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _masked(policy: dict[str, Any] | None, table: str) -> set[str]:
    out: set[str] = set()
    for entry in (policy or {}).get("applied", []) or []:
        if isinstance(entry, dict) and entry.get("table") in (table, "*documents*"):
            out.update(str(c) for c in (entry.get("masked_columns") or {}))
    return out


async def _export_kb(kb: KnowledgeBase, target: Path, warnings: list[str]) -> dict[str, Any]:
    kb_dir = target / str(kb.id)
    (kb_dir / "tables").mkdir(parents=True, exist_ok=True)
    files: list[dict[str, Any]] = []
    try:
        docs = await run_readonly(
            kb_id=kb.id,
            sql="SELECT id, filename, mime, size, pages, status, chunk_count FROM documents ORDER BY filename",
            limit=10_000,
            timeout_ms=60_000,
        )
        files = [dict(zip(docs.columns, row, strict=True)) for row in docs.rows]
    except KnowledgeError as exc:
        warnings.append(f"{kb.name}: no se ha podido leer la lista de documentos ({exc.message})")
    chunk_count = 0
    with (kb_dir / "chunks.jsonl").open("w", encoding="utf-8") as fh:
        offset = 0
        while offset < MAX_CHUNKS_PER_KB:
            try:
                page = await run_readonly(
                    kb_id=kb.id,
                    sql=(
                        "SELECT id, file_id, filename, ordinal, content, heading, page_from, page_to, metadata "
                        f"FROM chunks ORDER BY file_id, ordinal LIMIT {CHUNK_PAGE} OFFSET {offset}"
                    ),
                    limit=CHUNK_PAGE,
                    timeout_ms=60_000,
                )
            except KnowledgeError as exc:
                warnings.append(f"{kb.name}: fragmentos no exportados ({exc.message})")
                break
            for row in page.rows:
                record = dict(zip(page.columns, row, strict=True))
                meta = record.get("metadata")
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except json.JSONDecodeError:
                        meta = {"value": meta}
                record["metadata"] = meta or {}
                record["id"], record["file_id"] = str(record.get("id")), str(record.get("file_id"))
                fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            chunk_count += len(page.rows)
            if len(page.rows) < CHUNK_PAGE:
                break
            offset += CHUNK_PAGE
        else:
            warnings.append(f"{kb.name}: se han exportado los primeros {MAX_CHUNKS_PER_KB} fragmentos")

    async with system_session() as s:
        tables = (await s.execute(select(KbTable).where(KbTable.kb_id == kb.id).order_by(KbTable.name))).scalars().all()
        table_specs = [(t.name, t.description, dict(t.schema_json or {})) for t in tables]
    exported_tables: list[dict[str, Any]] = []
    for name, description, schema_json in table_specs:
        declared = [c for c in schema_json.get("columns", []) if isinstance(c, dict) and c.get("name")]
        primary_key = [str(c) for c in schema_json.get("primary_key", []) or []]
        types = {str(c["name"]): str(c.get("type") or "text") for c in declared}
        if not primary_key:
            types = {"_row_id": "integer", **types}
        order = ", ".join(quote_ident(c) for c in (primary_key or ["_row_id"]))
        stem = _TABLE_FILE_RE.sub("_", name)
        rows_written = 0
        columns: list[str] = []
        masked: set[str] = set()
        with (kb_dir / "tables" / f"{stem}.csv").open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            offset = 0
            failed = False
            while offset < MAX_ROWS_PER_TABLE:
                try:
                    page = await run_readonly(
                        kb_id=kb.id,
                        sql=f"SELECT * FROM {quote_ident(name)} ORDER BY {order} LIMIT {ROW_PAGE} OFFSET {offset}",
                        limit=ROW_PAGE,
                        timeout_ms=60_000,
                    )
                except KnowledgeError as exc:
                    warnings.append(f"{kb.name}.{name}: tabla no exportada ({exc.message})")
                    failed = True
                    break
                if not columns:
                    columns = list(page.columns)
                    masked = _masked(page.policy, name)
                    writer.writerow(columns)
                for row in page.rows:
                    writer.writerow([_csv_value(v) for v in row])
                rows_written += len(page.rows)
                if len(page.rows) < ROW_PAGE:
                    break
                offset += ROW_PAGE
            else:
                warnings.append(f"{kb.name}.{name}: se han exportado las primeras {MAX_ROWS_PER_TABLE} filas")
        if failed:
            (kb_dir / "tables" / f"{stem}.csv").unlink(missing_ok=True)
            continue
        schema = {
            "name": name,
            "description": description,
            "columns": [
                {"name": c, "type": "text" if c in masked else types.get(c, "text"), "masked": c in masked}
                for c in (columns or list(types))
            ],
            "primary_key": primary_key or ["_row_id"],
        }
        (kb_dir / "tables" / f"{stem}.schema.json").write_text(
            json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        exported_tables.append(
            {
                "name": name,
                "description": description,
                "csv": f"tables/{stem}.csv",
                "schema": f"tables/{stem}.schema.json",
                "row_count": rows_written,
            }
        )
    meta = {
        "id": str(kb.id),
        "name": kb.name,
        "description": kb.description,
        "governance_mode": kb.governance_mode,
        "files": json.loads(json.dumps(files, default=str)),
        "chunks": chunk_count,
        "tables": exported_tables,
    }
    (kb_dir / "kb.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


# ------------------------------------------------------------------------------------- generated files


def _compose(project: Project, members: list[Member], token: str, image: str) -> str:
    common_env = {
        "MESSER_ORG_ID": str(project.org_id),
        "MESSER_PROJECT_ID": str(project.id),
    }
    services: dict[str, Any] = {
        "platform": {
            "build": {"context": "."},
            "image": image,
            "command": ["python", "-m", "messer.platform.standalone", "--port", str(PLATFORM_PORT)],
            "environment": {
                **common_env,
                "MESSER_STANDALONE_TOKEN": f"${{MESSER_STANDALONE_TOKEN:-{token}}}",
                "MESSER_STANDALONE_DATA_DIR": "/app/data",
                "MESSER_STANDALONE_STATE_DIR": "/app/state",
                "MESSER_STANDALONE_MANIFEST": "/app/messer-export.json",
                "MESSER_STANDALONE_PUBLIC_URL": f"http://platform:{PLATFORM_PORT}",
                "ANTHROPIC_API_KEY": "${ANTHROPIC_API_KEY:-}",
                "SMTP_HOST": "${SMTP_HOST:-}",
                "SMTP_PORT": "${SMTP_PORT:-587}",
                "SMTP_USER": "${SMTP_USER:-}",
                "SMTP_PASSWORD": "${SMTP_PASSWORD:-}",
                "SMTP_TLS": "${SMTP_TLS:-true}",
                "EMAIL_FROM": "${EMAIL_FROM:-Messer <no-reply@localhost>}",
            },
            "ports": [f"127.0.0.1:{PLATFORM_PORT}:{PLATFORM_PORT}"],
            "volumes": ["platform-state:/app/state"],
            "healthcheck": {
                "test": [
                    "CMD",
                    "python",
                    "-c",
                    f"import urllib.request; urllib.request.urlopen('http://127.0.0.1:{PLATFORM_PORT}/healthcheck')",
                ],
                "interval": "5s",
                "timeout": "3s",
                "retries": 20,
            },
            "restart": "unless-stopped",
        }
    }
    for m in members:
        services[m.service] = {
            "build": {"context": "."},
            "image": image,
            "command": [
                "python",
                "-m",
                "messer.server",
                "--import_spec",
                f"/app/.messer/entrypoints/entry_{m.name}.py::runnable",
                "--host",
                "0.0.0.0",  # noqa: S104 - inside the container
                "--port",
                str(m.port),
            ],
            "environment": {
                **common_env,
                "MESSER_API_HOST": f"http://platform:{PLATFORM_PORT}/",
                "MESSER_API_KEY": f"${{MESSER_STANDALONE_TOKEN:-{token}}}",
            },
            "env_file": [{"path": "secrets.env", "required": False}],
            "ports": [f"127.0.0.1:{m.port}:{m.port}"],
            "depends_on": {"platform": {"condition": "service_healthy"}},
            "restart": "unless-stopped",
        }
    doc = {"name": project.slug, "services": services, "volumes": {"platform-state": {}}}
    header = (
        "# Generated by Messer. `docker compose up --build` starts the platform and every workforce member.\n"
        "# Ports are bound to localhost; see README.md to expose them.\n"
    )
    return header + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=200)


def _dockerfile(wheel_name: str) -> str:
    return (
        "# Generated by Messer: one image for the standalone platform and every workforce member.\n"
        "FROM python:3.12-slim\n"
        "ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1\n"
        "WORKDIR /app\n"
        "COPY vendor/ /app/vendor/\n"
        "COPY requirements.txt constraints.txt /app/\n"
        f'RUN pip install --constraint /app/constraints.txt "/app/vendor/{wheel_name}[server,evals]" '
        "-r /app/requirements.txt\n"
        "COPY project/ /app/project/\n"
        "COPY data/ /app/data/\n"
        "COPY .messer/ /app/.messer/\n"
        "COPY messer-export.json /app/messer-export.json\n"
        "RUN useradd --create-home --uid 10001 messer && mkdir -p /app/state && chown -R messer /app/state\n"
        "USER messer\n"
        "WORKDIR /app/project\n"
        f"EXPOSE {PLATFORM_PORT}\n"
    )


def _env_example(token: str) -> str:
    return (
        "# Copia este archivo a .env (docker compose lo lee automáticamente).\n"
        "# Copy this file to .env (docker compose reads it automatically).\n\n"
        "# Opcional / optional: sin clave, los agentes responden con el modelo offline de eco.\n"
        "ANTHROPIC_API_KEY=\n\n"
        "# Opcional / optional: envío de emails por SMTP (si no, se guardan en state/outbox.jsonl).\n"
        "SMTP_HOST=\nSMTP_PORT=587\nSMTP_USER=\nSMTP_PASSWORD=\nSMTP_TLS=true\nEMAIL_FROM=\n\n"
        "# Token local entre la plataforma y los miembros (generado para esta exportación).\n"
        "# Local token between the platform and the members (generated for this export).\n"
        f"MESSER_STANDALONE_TOKEN={token}\n"
    )


def _secrets_example(names: list[str]) -> str:
    lines = [
        "# Secretos del proyecto (no se exportan sus valores). Copia a secrets.env y rellénalos.",
        "# Project secrets (values are never exported). Copy to secrets.env and fill them in.",
    ]
    lines += [f"{n}=" for n in names] or ["# (el proyecto no tiene secretos / the project has no secrets)"]
    return "\n".join(lines) + "\n"


def _readme(project: Project, commit: str, members: list[Member], kbs: list[dict[str, Any]], wheel_name: str) -> str:
    rows = "\n".join(f"| `{m.name}` | {m.kind} | `http://localhost:{m.port}` |" for m in members) or "| — | — | — |"
    first = members[0] if members else None
    run_example = (
        f"curl -s http://localhost:{first.port}/run -H 'content-type: application/json' -d '{{\"prompt\": \"Hola\"}}'"
        if first and first.kind == "agent"
        else f"curl -s http://localhost:{first.port}/run -H 'content-type: application/json' -d '{{}}'"
        if first
        else "# (sin miembros / no members)"
    )
    stream_example = (
        f"curl -N http://localhost:{first.port}/stream -H 'content-type: application/json' "
        '-d \'{"prompt": "Hola"}\''
        if first and first.kind == "agent"
        else ""
    )
    kb_lines = "\n".join(f"- {kb['name']}: {kb['chunks']} fragmentos, {len(kb['tables'])} tablas" for kb in kbs)
    kb_lines = kb_lines or "- (ninguna / none)"
    return f"""# {project.name}

{project.description}

Exportación autónoma de Messer · Self-contained Messer export — commit `{commit[:12]}`.

| Miembro / member | Tipo / kind | URL |
|---|---|---|
{rows}

## Inicio rápido (español)

1. Opcional: `cp .env.example .env` y añade tu `ANTHROPIC_API_KEY`. Sin clave, los agentes responden con un
   **modelo offline de eco** (claramente etiquetado) que también consulta la base de conocimiento exportada.
2. `docker compose up --build`
3. Habla con un agente:

   ```bash
   {run_example}
   {stream_example}
   ```

La plataforma local (`http://localhost:{PLATFORM_PORT}`, servicio `platform`) guarda las trazas en el volumen
`platform-state` (`GET /traces` con `Authorization: Bearer $MESSER_STANDALONE_TOKEN`), busca en las bases de
conocimiento exportadas (palabras clave, BM25), ejecuta SQL de solo lectura sobre sus tablas (SQLite), envía
emails por SMTP (o los guarda en `state/outbox.jsonl`) y hace de proxy de Claude.

**Limitaciones:** las acciones de conectores (Gmail, HubSpot…) no están disponibles fuera de Messer y devuelven un
error claro; los valores de los secretos del proyecto no se exportan (rellena `secrets.env` a partir de
`secrets.env.example`); la búsqueda vectorial se sustituye por búsqueda por palabras clave; el SQL es SQLite.

Sin Docker: `python -m venv .venv && .venv/bin/pip install -c constraints.txt "vendor/{wheel_name}[server,evals]"
-r requirements.txt`, y lanza `python -m messer.platform.standalone` y `python -m messer.server --import_spec
.messer/entrypoints/entry_<miembro>.py::runnable --port 8001` con las variables de `docker-compose.yml`.

## Quick start (English)

1. Optional: `cp .env.example .env` and set your `ANTHROPIC_API_KEY`. Without a key the agents answer with a
   clearly labelled **offline echo model** that also searches the exported knowledge base.
2. `docker compose up --build`
3. Talk to an agent with the `curl` commands above (`/run` returns the final output, `/stream` streams events).

The local platform (`http://localhost:{PLATFORM_PORT}`, service `platform`) stores run traces in the
`platform-state` volume (`GET /traces` with `Authorization: Bearer $MESSER_STANDALONE_TOKEN`), searches the
exported knowledge bases (keyword/BM25), runs read-only SQL over their tables (SQLite), sends email through SMTP
(or saves it to `state/outbox.jsonl`) and proxies Claude.

**Limitations:** connector actions are not available outside Messer (they return a clear error); project secret
values are not exported (fill `secrets.env` from `secrets.env.example`); vector search becomes keyword search;
SQL runs on SQLite.

Without Docker: install the same command as above in a virtualenv, then run `python -m messer.platform.standalone`
and one `python -m messer.server --import_spec .messer/entrypoints/entry_<member>.py::runnable --port 8001` per
member, with the environment variables listed in `docker-compose.yml`.

Ports are bound to `127.0.0.1`. To expose a member, change its `ports` entry in `docker-compose.yml`.

## Conocimiento / knowledge

{kb_lines}
"""


# ------------------------------------------------------------------------------------------------ build


def validate_ref(ref: str) -> str:
    value = (ref or "HEAD").strip()
    if not _REF_RE.match(value) or value.startswith("-") or ".." in value:
        raise ApiError("Referencia de git no válida", code="invalid_ref")
    return value


async def build_export(session: AsyncSession, principal: Principal, project: Project, ref: str) -> ExportResult:
    repo = ProjectRepo.for_project(str(project.id))
    if not repo.exists:
        raise NotFound("El repositorio del proyecto no existe")
    try:
        commit = await repo.resolve(validate_ref(ref))
        archive = await repo.archive(commit)
    except RepoError as exc:
        raise NotFound("Referencia no encontrada") from exc
    wheel = await engine_wheel()
    work = Path(tempfile.mkdtemp(prefix="export-", dir=get_settings().runtime_cache_dir))
    try:
        root = work / project.slug
        project_dir = root / "project"
        await asyncio.to_thread(_safe_extract, archive, project_dir)
        members = discover_members(project_dir)
        warnings: list[str] = []
        kb_target = root / "data" / "knowledge"
        kb_target.mkdir(parents=True, exist_ok=True)
        kb_meta: list[dict[str, Any]] = []
        for kb in await linked_knowledge_bases(project, project_dir):
            kb_meta.append(await _export_kb(kb, kb_target, warnings))
        (kb_target / "index.json").write_text(
            json.dumps(
                {
                    "knowledge_bases": [
                        {"id": k["id"], "name": k["name"], "description": k["description"]} for k in kb_meta
                    ]
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        secret_names = sorted(
            (await session.execute(select(Secret.name).where(Secret.project_id == project.id))).scalars()
        )
        requirements, req_warnings = _project_requirements(project_dir)
        warnings += req_warnings
        token = secrets.token_urlsafe(24)
        image = f"{project.slug}-messer:{commit[:12]}"
        entry_dir = root / ".messer" / "entrypoints"
        entry_dir.mkdir(parents=True, exist_ok=True)
        for m in members:
            (entry_dir / f"entry_{m.name}.py").write_text(entrypoint_source(m), encoding="utf-8")
        (root / "vendor").mkdir()
        await asyncio.to_thread(shutil.copy2, wheel, root / "vendor" / wheel.name)
        manifest = {
            "format": FORMAT,
            "generated_at": datetime.now(UTC).isoformat(),
            "generated_by": principal.email,
            "project": {
                "id": str(project.id),
                "org_id": str(project.org_id),
                "name": project.name,
                "slug": project.slug,
                "description": project.description,
            },
            "ref": ref,
            "commit": commit,
            "engine": {"wheel": f"vendor/{wheel.name}", "version": _engine_version(_engine_root())},
            "platform": {
                "service": "platform",
                "port": PLATFORM_PORT,
                "command": "python -m messer.platform.standalone",
            },
            "members": [
                {
                    "name": m.name,
                    "kind": m.kind,
                    "service": m.service,
                    "port": m.port,
                    "entrypoint": f".messer/entrypoints/entry_{m.name}.py::runnable",
                    "url": f"http://localhost:{m.port}",
                }
                for m in members
            ],
            "knowledge_bases": [
                {"id": k["id"], "name": k["name"], "chunks": k["chunks"], "tables": [t["name"] for t in k["tables"]]}
                for k in kb_meta
            ],
            "secrets": secret_names,
            "warnings": warnings,
        }
        texts = {
            "messer-export.json": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            "docker-compose.yml": _compose(project, members, token, image),
            "Dockerfile": _dockerfile(wheel.name),
            ".dockerignore": ".env\nsecrets.env\nstate/\n**/__pycache__\n**/.venv\n",
            ".env.example": _env_example(token),
            "secrets.env.example": _secrets_example(secret_names),
            "requirements.txt": "# Extra dependencies of the project (the engine is installed from vendor/).\n"
            + "".join(f"{r}\n" for r in requirements),
            "constraints.txt": "# Versions tested with this Messer build.\n"
            + "".join(f"{c}\n" for c in pinned_constraints()),
            "README.md": _readme(project, commit, members, kb_meta, wheel.name),
        }
        for name, content in texts.items():
            (root / name).write_text(content, encoding="utf-8")
        filename = f"{project.slug}-{commit[:7]}.zip"
        zip_path = work / filename
        await asyncio.to_thread(_zip_dir, root, zip_path)
        shutil.rmtree(root, ignore_errors=True)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    await audit.record(
        session,
        action="project.exported",
        principal=principal,
        entity_type="project",
        entity_id=project.id,
        diff={
            "commit": commit,
            "ref": ref,
            "members": [m.name for m in members],
            "knowledge_bases": [k["id"] for k in kb_meta],
        },
    )
    return ExportResult(
        path=zip_path, filename=filename, commit=commit, size=zip_path.stat().st_size, manifest=manifest
    )


def _zip_dir(root: Path, target: Path) -> None:
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(root.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            arc = f"{root.name}/{path.relative_to(root).as_posix()}"
            compress = zipfile.ZIP_STORED if path.suffix == ".whl" else zipfile.ZIP_DEFLATED
            zf.write(path, arc, compress_type=compress)


async def stream_file(path: Path, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
    """Stream a finished export and delete its working directory afterwards."""
    try:
        with path.open("rb") as fh:
            while True:
                chunk = await asyncio.to_thread(fh.read, chunk_size)
                if not chunk:
                    break
                yield chunk
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)
