"""Cloning industry templates into ready-to-run projects (spec 8.4).

``clone_template`` turns a template directory (see :mod:`.templates_catalog`) into a project of the caller's
organization:

1. knowledge bases are created and filled first — sample documents rendered as labelled PDFs and queued for
   ingestion, sample tables loaded with their column types (dates shifted so the sample data is current);
2. one transaction creates the project with every file in a single initial commit (agents and workflows rendered
   from their configs with the new knowledge base ids, tools, custom nodes, layouts, evals, interfaces,
   ``knowledge.yaml``, ``triggers.yaml``, README), its workforce rows, triggers (cron ones disabled unless the
   template marks them safe) and channels in demo mode, and links the knowledge bases to the project;
3. the interfaces are indexed from the repository.

If step 2 fails, the knowledge bases of step 1 and the repository directory are removed, so a failed clone leaves
nothing behind. Document ingestion continues in the worker; the project is usable immediately.
"""

from __future__ import annotations

import html
import io
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import yaml
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common import triggers as triggers_mod
from messer_common.db import Principal, rls_session, system_session
from messer_common.db.models import KnowledgeBase, Project, Trigger, Workforce
from messer_common.knowledge.errors import KnowledgeError
from messer_common.logging import get_logger
from messer_common.projects_repo import ProjectRepo
from messer_common.studio.agent_spec import AgentConfig
from messer_common.studio.project_files import agent_member_files
from messer_common.studio.workflow_spec import (
    CUSTOM_NODES_FILE,
    WorkflowConfig,
    auto_layout,
    custom_nodes_template,
    parse_custom_nodes,
    stored_config,
    with_positions,
    workflow_member_files,
)

from ..errors import ApiError, NotFound, PlanLimitExceeded
from . import channels as channels_svc
from . import interfaces as interfaces_svc
from . import limits
from . import projects as projects_svc
from .knowledge import create_kb, delete_kb, ingest_bytes, upsert_table
from .knowledge.common import to_api_error
from .templates_catalog import (
    TOOLS_FILE,
    DocumentSpec,
    LoadedTemplate,
    TableSpec,
    TemplateManifest,
    all_templates,
    get_template,
    match_scores,
    match_template,
    parse_agent,
    parse_workflow,
    read_table_rows,
    substitute,
)

log = get_logger("messer.api.templates")

__all__ = [
    "CloneResult",
    "all_templates",
    "clone_template",
    "get_template",
    "match_scores",
    "match_template",
    "render_document",
]

SAMPLE_LABEL = "Documento de ejemplo · Plantilla de Messer · Sustitúyelo por el tuyo"
EVAL_ENTRY_FILE = "evals/_member.py"
EVAL_ENTRY = '''"""Loads this agent as a package module, so evals run it exactly like the runtime does (``from . import
tools`` inside ``agent.py`` needs the package). Referenced by the eval files as ``_member.py::agent``."""

import importlib
import sys
from pathlib import Path

_MEMBER = Path(__file__).resolve().parent.parent
_PROJECT = _MEMBER.parent.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

agent = importlib.import_module(f"{_MEMBER.parent.name}.{_MEMBER.name}.agent").agent
'''


@dataclass(slots=True)
class CloneResult:
    project: Project
    knowledge_bases: list[dict[str, Any]] = field(default_factory=list)
    members: list[dict[str, Any]] = field(default_factory=list)
    interfaces: list[str] = field(default_factory=list)
    channels: list[dict[str, Any]] = field(default_factory=list)
    triggers: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[dict[str, str]] = field(default_factory=list)  # {code, message, message_en}


# ============================================================================================ sample documents

_HEADING = re.compile(r"^(#{1,3})\s+(.+)$")
_BULLET = re.compile(r"^[-*]\s+(.+)$")
_NUMBERED = re.compile(r"^\d+[.)]\s+(.+)$")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_CODE = re.compile(r"`([^`]+)`")

_PDF_CSS = """
body { font-family: sans-serif; font-size: 10.5pt; line-height: 1.45; color: #111111; }
h1 { font-size: 19pt; margin: 0 0 6pt 0; }
h2 { font-size: 13pt; margin: 14pt 0 4pt 0; }
h3 { font-size: 11pt; margin: 10pt 0 3pt 0; }
p { margin: 0 0 6pt 0; }
li { margin: 0 0 3pt 0; }
table { border-collapse: collapse; margin: 6pt 0; }
th, td { border: 1px solid #bbbbbb; padding: 3pt 5pt; font-size: 9.5pt; }
th { background-color: #f2f2f2; }
"""


def _inline(text: str) -> str:
    out = html.escape(text, quote=False)
    out = _BOLD.sub(r"<b>\1</b>", out)
    return _CODE.sub(r"<code>\1</code>", out)


def markdown_html(text: str) -> str:
    """The Markdown subset of the sample documents (headings, paragraphs, lists, tables, bold) as HTML."""
    blocks: list[str] = []
    paragraph: list[str] = []
    items: list[str] = []
    list_tag: str | None = None
    table: list[list[str]] = []

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(f"<p>{_inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    def flush_list() -> None:
        nonlocal list_tag
        if list_tag and items:
            blocks.append(f"<{list_tag}>" + "".join(f"<li>{_inline(i)}</li>" for i in items) + f"</{list_tag}>")
        items.clear()
        list_tag = None

    def flush_table() -> None:
        if table:
            head, *rows = table
            cells = "".join(f"<th>{_inline(c)}</th>" for c in head)
            body = "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in rows)
            blocks.append(f"<table><tr>{cells}</tr>{body}</table>")
            table.clear()

    def flush() -> None:
        flush_paragraph()
        flush_list()
        flush_table()

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        if line.startswith("|"):
            flush_paragraph()
            flush_list()
            cells = [c.strip() for c in line.strip("|").split("|")]
            if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                table.append(cells)
            continue
        flush_table()
        heading = _HEADING.match(line)
        if heading:
            flush()
            level = len(heading.group(1))
            blocks.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue
        bullet, numbered = _BULLET.match(line), _NUMBERED.match(line)
        if bullet or numbered:
            flush_paragraph()
            tag = "ul" if bullet else "ol"
            if list_tag != tag:
                flush_list()
                list_tag = tag
            items.append((bullet or numbered).group(1))  # type: ignore[union-attr]
            continue
        if list_tag and raw.startswith(("  ", "\t")) and items:
            items[-1] = f"{items[-1]} {line}"
            continue
        flush_list()
        paragraph.append(line)
    flush()
    return "\n".join(blocks)


def render_pdf(markdown: str, *, title: str, template_name: str) -> bytes:
    """A4 PDF of a sample document, labelled as an example on every page (PyMuPDF, deterministic metadata)."""
    import fitz

    buffer = io.BytesIO()
    story: Any = fitz.Story(html=markdown_html(markdown), user_css=_PDF_CSS)
    writer: Any = fitz.DocumentWriter(buffer)
    mediabox = fitz.paper_rect("a4")
    where = fitz.Rect(56, 72, mediabox.width - 56, mediabox.height - 64)
    more = 1
    pages = 0
    while more:
        device = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
        pages += 1
        if pages > 50:
            break
    writer.close()
    doc: Any = fitz.open("pdf", buffer.getvalue())
    total = len(doc)
    for index, page in enumerate(doc):
        page.insert_text((56, 40), SAMPLE_LABEL.upper(), fontsize=7, color=(0.835, 0.169, 0.118))
        page.insert_text(
            (56, mediabox.height - 32),
            f"{title} · {template_name} · Página {index + 1} de {total}",
            fontsize=7.5,
            color=(0.4, 0.4, 0.4),
        )
    stamp = "D:20260101000000Z"
    doc.set_metadata(
        {
            "title": title,
            "author": "Messer (documento de ejemplo)",
            "subject": SAMPLE_LABEL,
            "creator": "Messer",
            "producer": "Messer",
            "creationDate": stamp,
            "modDate": stamp,
        }
    )
    data = bytes(doc.tobytes(garbage=3, deflate=True))
    doc.close()
    return data


def render_document(template: LoadedTemplate, doc: DocumentSpec) -> tuple[bytes, str]:
    """(content, mime) of a sample document: a PDF rendered from its Markdown source, or the Markdown itself."""
    source = (template.root / doc.source).read_text(encoding="utf-8")
    if doc.filename.lower().endswith(".pdf"):
        return render_pdf(source, title=doc.title, template_name=template.manifest.name), "application/pdf"
    return f"> {SAMPLE_LABEL}\n\n{source}".encode(), "text/markdown"


# ============================================================================================ sample tables


def _shift(value: str, kind: str, delta: timedelta) -> str:
    if kind == "date":
        return (date.fromisoformat(value) + delta).isoformat()
    return (datetime.fromisoformat(value) + delta).isoformat()


def table_rows(template: LoadedTemplate, table: TableSpec, today: date) -> list[dict[str, Any]]:
    """Rows of a sample table, with date and timestamp columns moved forward so ``date_anchor`` is ``today``."""
    rows = read_table_rows(template, table)
    if table.date_anchor is None:
        return rows
    delta = today - table.date_anchor
    if table.date_shift == "weeks":
        delta = timedelta(weeks=round(delta.days / 7))
    shifted = [c for c in table.columns if c.type in ("date", "timestamp")]
    for row in rows:
        for column in shifted:
            value = row.get(column.name)
            if value:
                row[column.name] = _shift(str(value), column.type, delta)
    return rows


# ============================================================================================ project files


def _yaml(data: Any) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)


@dataclass(slots=True)
class _Member:
    id: uuid.UUID
    name: str
    kind: str
    description: str
    config_json: dict[str, Any]
    files: dict[str, str]


def _agent_member(template: LoadedTemplate, name: str, kb_ids: dict[str, str]) -> _Member:
    files_spec = template.member(name)
    assert files_spec is not None
    config: AgentConfig = parse_agent(files_spec.config_text, kb_ids)
    if config.model_tier is None and config.model is None:
        config.model_tier = template.manifest.default_model_tier
    member_id = uuid.uuid4()
    files = agent_member_files(member_id=str(member_id), config=config)
    base = f"workforce/{name}"
    if files_spec.evals:
        files.pop(f"{base}/evals/basic.yaml", None)
        files[f"{base}/{EVAL_ENTRY_FILE}"] = EVAL_ENTRY
    for path, text in files_spec.evals.items():
        files[f"{base}/{path}"] = substitute(text, kb_ids)
    if TOOLS_FILE in files_spec.extra:
        files[f"{base}/{TOOLS_FILE}"] = substitute(files_spec.extra[TOOLS_FILE], kb_ids)
    return _Member(member_id, name, "agent", config.description, config.model_dump(mode="json"), files)


def _workflow_member(template: LoadedTemplate, name: str, kb_ids: dict[str, str]) -> _Member:
    files_spec = template.member(name)
    assert files_spec is not None
    config: WorkflowConfig = parse_workflow(files_spec.config_text, kb_ids)
    nodes_code = substitute(files_spec.extra.get(CUSTOM_NODES_FILE) or custom_nodes_template(name), kb_ids)
    functions = [f.name for f in parse_custom_nodes(nodes_code)]
    placed = {n.id: n.position for n in config.nodes if n.position is not None}
    config = with_positions(config.model_copy(update={"custom_nodes": functions}), {**auto_layout(config), **placed})
    member_id = uuid.uuid4()
    files = workflow_member_files(member_id=str(member_id), config=config, nodes_code=nodes_code)
    for path, text in files_spec.evals.items():
        files[f"workforce/{name}/{path}"] = substitute(text, kb_ids)
    return _Member(member_id, name, "workflow", config.description, stored_config(config), files)


def _readme(template: LoadedTemplate, project_name: str) -> str:
    return template.readme.replace("${project_name}", project_name)


def _project_files(
    template: LoadedTemplate,
    *,
    project_name: str,
    members: list[_Member],
    kbs: list[tuple[str, KnowledgeBase]],
    kb_ids: dict[str, str],
) -> dict[str, str]:
    files: dict[str, str] = {}
    for member in members:
        files.update(member.files)
    for slug, text in template.interfaces.items():
        files[f"interfaces/{slug}/interface.json"] = substitute(text, kb_ids)
    files["knowledge.yaml"] = "# Knowledge bases linked to this project\n" + _yaml(
        {"knowledge_bases": [{"key": key, "id": str(kb.id), "name": kb.name} for key, kb in kbs]}
    )
    files["triggers.yaml"] = "# Workflow triggers\n" + _yaml(
        {
            "triggers": [
                {
                    "name": t.name,
                    "workforce": t.member,
                    "kind": t.kind,
                    "enabled": t.enabled,
                    "environment": t.environment,
                    "config": {k: substitute(str(v), kb_ids) if isinstance(v, str) else v for k, v in t.config.items()},
                }
                for t in template.manifest.triggers
            ]
        }
    )
    files["README.md"] = _readme(template, project_name)
    files["interfaces/.gitkeep"] = ""
    return files


# ============================================================================================ clone


def _trigger_config(spec_config: dict[str, Any], kb_ids: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in spec_config.items():
        out[key] = substitute(value, kb_ids) if isinstance(value, str) else value
    return out


async def _create_triggers(
    session: AsyncSession,
    principal: Principal,
    project: Project,
    manifest: TemplateManifest,
    members: dict[str, _Member],
    kb_ids: dict[str, str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for spec in manifest.triggers:
        member = members[spec.member]
        config = triggers_mod.validate_config(spec.kind, _trigger_config(spec.config, kb_ids))
        trigger = Trigger(
            org_id=project.org_id,
            project_id=project.id,
            workforce_id=member.id,
            kind=spec.kind,
            name=spec.name,
            config=config,
            environment=spec.environment,
            enabled=spec.enabled,
        )
        secret: str | None = None
        if spec.kind == "webhook":
            secret, trigger.secret = triggers_mod.new_secret()
        if spec.kind == "cron" and trigger.enabled:
            trigger.next_fire_at = triggers_mod.next_cron(config["expression"], config.get("timezone", "Europe/Madrid"))
        session.add(trigger)
        await session.flush()
        await audit.record(
            session,
            action="trigger.created",
            principal=principal,
            entity_type="trigger",
            entity_id=trigger.id,
            diff={"kind": spec.kind, "workforce": member.name, "template": manifest.id, "enabled": trigger.enabled},
        )
        described = triggers_mod.describe(trigger)
        if secret:
            described["secret"] = secret  # shown once, like the triggers API
        out.append(described)
    return out


async def _create_channels(
    session: AsyncSession, principal: Principal, project: Project, manifest: TemplateManifest, warnings: list[str]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for spec in manifest.channels:
        body = channels_svc.ChannelIn(provider=spec.provider, workforce=spec.agent, name=spec.name, demo=True)
        try:
            created = await channels_svc.connect(session, principal, project, body)
        except PlanLimitExceeded as exc:
            warnings.append(f"No se ha creado el canal {spec.provider}: {exc.message}")
            continue
        data = created.model_dump(mode="json")
        data.pop("webhook_secret", None)
        out.append(data)
    return out


async def _drop_knowledge_bases(principal: Principal, kb_ids: list[uuid.UUID]) -> None:
    for kb_id in kb_ids:
        try:
            await delete_kb(principal, kb_id)
        except Exception as exc:  # cleanup is best effort: the original error is what the caller sees
            log.warning("templates.cleanup_kb_failed", kb_id=str(kb_id), error=str(exc)[:300])


async def _fill_knowledge(
    template: LoadedTemplate, principal: Principal, kbs: list[tuple[str, KnowledgeBase]], today: date
) -> list[dict[str, Any]]:
    assert principal.org_id is not None
    summary: list[dict[str, Any]] = []
    specs = {kb.key: kb for kb in template.manifest.knowledge_bases}
    async with system_session() as s:
        for key, kb in kbs:
            spec = specs[key]
            documents: list[dict[str, Any]] = []
            for doc in spec.documents:
                data, mime = render_document(template, doc)
                file = await ingest_bytes(
                    s,
                    org_id=principal.org_id,
                    kb_id=kb.id,
                    filename=doc.filename,
                    data=data,
                    mime=mime,
                    source="template",
                    external_id=f"template:{template.id}:{doc.filename}",
                    uploaded_by=principal.user_id,
                )
                documents.append({"id": str(file.id), "filename": file.filename, "status": file.status})
            tables: list[dict[str, Any]] = []
            for table in spec.tables:
                rows = table_rows(template, table, today)
                loaded = await upsert_table(
                    s,
                    org_id=principal.org_id,
                    kb_id=kb.id,
                    table=table.name,
                    columns=[c.model_dump(mode="json") for c in table.columns],
                    rows=rows,
                    primary_key=list(table.primary_key),
                    source="template",
                    description=table.description,
                )
                tables.append({"name": loaded.name, "rows": loaded.row_count})
            summary.append({"key": key, "id": str(kb.id), "name": kb.name, "documents": documents, "tables": tables})
    return summary


async def clone_template(
    principal: Principal,
    template_id: str,
    *,
    name: str,
    description: str | None = None,
    today: date | None = None,
) -> CloneResult:
    """Create a ready-to-run project of ``principal``'s organization from a template (role checked by caller)."""
    template = get_template(template_id)
    if template is None:
        raise NotFound("Plantilla no encontrada", code="template_not_found")
    if principal.org_id is None:
        raise ApiError("Selecciona una organización", code="no_active_org")
    project_name = name.strip()
    if not project_name:
        raise ApiError("El nombre del proyecto es obligatorio", code="invalid_name", status_code=422)
    manifest = template.manifest
    async with rls_session(principal) as s:
        await limits.require_project_capacity(s, principal.org_id)

    kbs: list[tuple[str, KnowledgeBase]] = []
    repo: ProjectRepo | None = None
    try:
        try:
            for spec in manifest.knowledge_bases:
                kb = await create_kb(
                    principal, name=f"{spec.name} · {project_name}"[:200], description=spec.description
                )
                kbs.append((spec.key, kb))
            kb_ids = {key: str(kb.id) for key, kb in kbs}
            kb_summary = await _fill_knowledge(template, principal, kbs, today or datetime.now(UTC).date())
        except KnowledgeError as exc:
            raise to_api_error(exc) from exc

        members = [
            _agent_member(template, m.name, kb_ids) if m.kind == "agent" else _workflow_member(template, m.name, kb_ids)
            for m in template.members
        ]
        by_name = {m.name: m for m in members}
        files = _project_files(template, project_name=project_name, members=members, kbs=kbs, kb_ids=kb_ids)
        warnings: list[str] = []
        async with rls_session(principal) as s:
            project = await projects_svc.create_project(
                s,
                principal,
                name=project_name,
                description=(description or manifest.description).strip()[:2000],
                default_model_tier=manifest.default_model_tier,
                template_id=manifest.id,
                files=files,
            )
            repo = projects_svc.repo_for(project)
            for member in members:
                s.add(
                    Workforce(
                        id=member.id,
                        org_id=project.org_id,
                        project_id=project.id,
                        kind=member.kind,
                        name=member.name,
                        description=member.description,
                        path=f"workforce/{member.name}",
                        config_json=member.config_json,
                        source_mode="config",
                    )
                )
            await s.flush()
            await s.execute(
                update(KnowledgeBase)
                .where(KnowledgeBase.id.in_([kb.id for _, kb in kbs]), KnowledgeBase.org_id == project.org_id)
                .values(project_id=project.id)
            )
            await projects_svc.update_manifest(
                s,
                principal,
                project,
                {
                    "template": {"id": manifest.id, "version": manifest.version},
                    "channels": [{"provider": c.provider, "workforce": c.agent} for c in manifest.channels],
                },
            )
            trigger_rows = await _create_triggers(s, principal, project, manifest, by_name, kb_ids)
            channel_rows = await _create_channels(s, principal, project, manifest, warnings)
            await audit.record(
                s,
                action="template.cloned",
                principal=principal,
                entity_type="project",
                entity_id=project.id,
                diff={
                    "template": manifest.id,
                    "version": manifest.version,
                    "members": [m.name for m in members],
                    "knowledge_bases": [str(kb.id) for _, kb in kbs],
                    "channels": [c["provider"] for c in channel_rows],
                    "triggers": len(trigger_rows),
                },
            )
            await s.flush()
            await s.refresh(project)
            s.expunge(project)
    except Exception:
        await _drop_knowledge_bases(principal, [kb.id for _, kb in kbs])
        if repo is not None and repo.path.exists():
            shutil.rmtree(repo.path, ignore_errors=True)
        raise

    try:
        await interfaces_svc.sync_index(project)
    except Exception as exc:  # the files are committed: the index is rebuilt on the next interface request
        log.warning("templates.interfaces_index_failed", project_id=str(project.id), error=str(exc)[:300])
        warnings.append("Las interfaces se indexarán al abrirlas")
    notes: list[dict[str, str]] = []
    if manifest.phone is not None:
        notes.append({"code": "phone", "message": manifest.phone.note, "message_en": manifest.phone.note_en})
    if any(t.kind == "cron" and not t.enabled for t in manifest.triggers):
        notes.append(
            {
                "code": "cron_disabled",
                "message": "Los disparadores programados se crean desactivados: actívalos en el flujo cuando quieras.",
                "message_en": "Scheduled triggers are created disabled: enable them on the workflow when you want.",
            }
        )
    log.info("templates.cloned", template=manifest.id, project_id=str(project.id), org_id=str(project.org_id))
    return CloneResult(
        project=project,
        knowledge_bases=kb_summary,
        members=[{"name": m.name, "kind": m.kind, "id": str(m.id)} for m in members],
        interfaces=sorted(template.interfaces),
        channels=channel_rows,
        triggers=trigger_rows,
        warnings=warnings,
        notes=notes,
    )


async def template_projects(session: AsyncSession, template_id: str) -> list[Project]:
    """Projects of the session's organization cloned from ``template_id`` (RLS session)."""
    rows = await session.execute(
        select(Project)
        .where(Project.template_id == template_id, Project.archived_at.is_(None))
        .order_by(Project.created_at.desc())
        .limit(20)
    )
    return list(rows.scalars().all())
