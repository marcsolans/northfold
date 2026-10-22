"""Industry templates catalog: the template directories in ``packages/templates`` and the ``templates`` table.

A template directory is a complete project definition (spec 8.4)::

    <id>/template.yaml                       manifest: names, sector, knowledge, channels, triggers, requirements
    <id>/plan.json                           the Composer plan the template implements (messer_common.composer.plan)
    <id>/README.md                           README of the cloned project (``${project_name}`` is replaced)
    <id>/knowledge/<kb>/*.md|*.csv           sample documents (rendered to labelled PDFs) and tables
    <id>/workforce/<agent>/agent.yaml        AgentConfig (+ tools.py, evals/*.yaml)
    <id>/workforce/<workflow>/workflow.yaml  WorkflowConfig with node positions (+ nodes.py, evals/*.yaml)
    <id>/interfaces/<slug>/interface.json    InterfaceSpec

Text files may reference what only exists after cloning: ``${kb:<key>}`` (knowledge base id), ``${model:<tier>}``
(model id from ``config/models.yaml``) and ``${project_name}``. :func:`load_template` validates everything with
those placeholders filled with stand-ins, so a broken template fails loudly at seed time and in tests, never
half-way through a clone.

The database row (``templates``) is the published catalog entry: content comes from the directory, while
``public`` and ``sort_order`` belong to the backoffice and are never overwritten by seeding.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.composer.plan import Plan, validate_plan
from messer_common.db.models import Template
from messer_common.interfaces import validate_interface
from messer_common.interfaces.validation import InterfaceValidationError
from messer_common.logging import get_logger
from messer_common.models_config import TIERS, resolve_model
from messer_common.settings import REPO_ROOT
from messer_common.studio.agent_spec import BUILTIN_TOOLS, AgentConfig
from messer_common.studio.workflow_spec import (
    CUSTOM_NODES_FILE,
    WorkflowConfig,
    parse_custom_nodes,
    validate_workflow,
)

log = get_logger("messer.api.templates")

TEMPLATE_FILE = "template.yaml"
PLAN_FILE = "plan.json"
README_FILE = "README.md"
AGENT_FILE = "agent.yaml"
WORKFLOW_FILE = "workflow.yaml"
TOOLS_FILE = "tools.py"
INTERFACE_FILE = "interface.json"
OFFLINE_EVAL_TAG = "offline"  # deterministic evals: pass with the offline demo model
LLM_EVAL_TAG = "llm"  # graded by an LLM judge: skipped while no model provider key is configured

SECTORS: tuple[str, ...] = (
    "finance",
    "sales",
    "back_office",
    "hr",
    "legal",
    "operations",
    "phone",
    "sales_leadership",
)

_IDENT = r"^[a-z][a-z0-9_]{0,62}$"
_SLUG = r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$"
_PLACEHOLDER = re.compile(r"\$\{(kb|model):([a-z][a-z0-9_]*)\}")
_DUMMY_NAMESPACE = uuid.UUID("6f4b8f7e-9a51-4a7e-8f0e-6d6573736572")


def templates_dir() -> Path:
    """Root of the template directories (``MESSER_TEMPLATES_DIR`` overrides ``packages/templates``)."""
    override = os.environ.get("MESSER_TEMPLATES_DIR", "").strip()
    return Path(override) if override else REPO_ROOT / "packages" / "templates"


class TemplateError(ValueError):
    """A template directory is missing or inconsistent (raised while loading, never during a clone)."""

    def __init__(self, template_id: str, problems: list[str]) -> None:
        super().__init__(f"{template_id}: " + "; ".join(problems[:8]))
        self.template_id = template_id
        self.problems = problems


# ================================================================================================ manifest


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentSpec(_Spec):
    source: str = Field(description="Markdown source inside the template directory")
    filename: str = Field(description="Name of the ingested file (.pdf rendered from the source, or .md)")
    title: str

    @field_validator("filename")
    @classmethod
    def _filename(cls, value: str) -> str:
        if "/" in value or not value.lower().endswith((".pdf", ".md")):
            raise ValueError("filename must be a plain .pdf or .md file name")
        return value


ColumnType = Literal["text", "integer", "numeric", "boolean", "date", "timestamp", "json"]


class ColumnSpec(_Spec):
    name: str = Field(pattern=_IDENT)
    type: ColumnType = "text"
    comment: str = ""
    nullable: bool = True


class TableSpec(_Spec):
    name: str = Field(pattern=_IDENT)
    source: str = Field(description="CSV file (comma separated, header row, ISO dates, dot decimals)")
    description: str = ""
    primary_key: list[str] = Field(default_factory=list)
    columns: list[ColumnSpec] = Field(min_length=1)
    date_anchor: date | None = Field(
        default=None,
        description="Sample dates are shifted so that this date becomes the day of the clone (data stays current)",
    )
    date_shift: Literal["days", "weeks"] = Field(
        default="days", description="weeks: shift by whole weeks so weekdays (opening hours, weekly reports) hold"
    )

    @model_validator(mode="after")
    def _keys(self) -> TableSpec:
        names = [c.name for c in self.columns]
        missing = [k for k in self.primary_key if k not in names]
        if missing:
            raise ValueError(f"primary key columns not declared: {', '.join(missing)}")
        return self


class KnowledgeBaseSpec(_Spec):
    key: str = Field(pattern=_IDENT)
    name: str = Field(min_length=1, max_length=120)
    name_en: str = Field(min_length=1, max_length=120)
    description: str = ""
    description_en: str = ""
    documents: list[DocumentSpec] = Field(default_factory=list)
    tables: list[TableSpec] = Field(default_factory=list)


class ChannelSpec(_Spec):
    provider: Literal["whatsapp", "slack", "teams", "telegram", "email"]
    agent: str = Field(pattern=_IDENT)
    name: str = ""


class TriggerSpec(_Spec):
    member: str = Field(pattern=_IDENT)
    kind: Literal["cron", "webhook", "email", "file", "connector_event"]
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    environment: Literal["production", "development"] = "production"


class RequirementSpec(_Spec):
    kind: Literal["connector", "key"]
    key: str = Field(min_length=1, max_length=120, description="Connector catalog key or environment variable")
    purpose: str
    purpose_en: str
    required: bool = False


class PhoneSpec(_Spec):
    agent: str = Field(pattern=_IDENT)
    note: str
    note_en: str


class PromptSpec(_Spec):
    member: str = Field(pattern=_IDENT)
    prompt: str
    prompt_en: str


class TemplateManifest(_Spec):
    id: str = Field(pattern=_SLUG)
    version: int = Field(default=1, ge=1)
    sector: Literal["finance", "sales", "back_office", "hr", "legal", "operations", "phone", "sales_leadership"]
    sort_order: int = Field(default=100, ge=0, le=10_000)
    name: str = Field(min_length=1, max_length=200)
    name_en: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    description_en: str = Field(min_length=1, max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=12)
    keywords: list[str] = Field(default_factory=list, description="Weighted terms for match_template (word:weight)")
    includes: list[str] = Field(default_factory=list, max_length=8)
    includes_en: list[str] = Field(default_factory=list, max_length=8)
    default_model_tier: Literal["fast", "standard", "powerful"] = "standard"
    knowledge_bases: list[KnowledgeBaseSpec] = Field(default_factory=list)
    channels: list[ChannelSpec] = Field(default_factory=list)
    triggers: list[TriggerSpec] = Field(default_factory=list)
    requirements: list[RequirementSpec] = Field(default_factory=list)
    phone: PhoneSpec | None = None
    try_prompts: list[PromptSpec] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _consistent(self) -> TemplateManifest:
        if len(self.includes) != len(self.includes_en):
            raise ValueError("includes and includes_en must have the same length")
        keys = [k.key for k in self.knowledge_bases]
        if len(keys) != len(set(keys)):
            raise ValueError("knowledge base keys must be unique")
        return self


# ================================================================================================ loaded


@dataclass(slots=True)
class MemberFiles:
    """A workforce member of a template: its configuration (raw text with placeholders) and extra files."""

    name: str
    kind: Literal["agent", "workflow"]
    config_text: str
    extra: dict[str, str] = field(default_factory=dict)  # relative path inside the member → text (tools.py…)
    evals: dict[str, str] = field(default_factory=dict)  # evals/<file>.yaml → text


@dataclass(slots=True)
class LoadedTemplate:
    root: Path
    manifest: TemplateManifest
    plan: Plan
    readme: str
    members: list[MemberFiles]
    interfaces: dict[str, str]  # slug → interface.json text
    summary: dict[str, Any]

    @property
    def id(self) -> str:
        return self.manifest.id

    def member(self, name: str) -> MemberFiles | None:
        return next((m for m in self.members if m.name == name), None)


def substitute(text: str, kb_ids: dict[str, str]) -> str:
    """Replace ``${kb:key}`` and ``${model:tier}`` placeholders. Raises ``KeyError`` for unknown names."""

    def repl(match: re.Match[str]) -> str:
        kind, name = match.group(1), match.group(2)
        if kind == "kb":
            return kb_ids[name]
        if name not in TIERS:
            raise KeyError(f"model tier {name}")
        return resolve_model(name)

    return _PLACEHOLDER.sub(repl, text)


def stand_in_kb_ids(manifest: TemplateManifest) -> dict[str, str]:
    """Deterministic UUIDs used to validate configs before any knowledge base exists."""
    return {kb.key: str(uuid.uuid5(_DUMMY_NAMESPACE, f"{manifest.id}:{kb.key}")) for kb in manifest.knowledge_bases}


def parse_agent(text: str, kb_ids: dict[str, str]) -> AgentConfig:
    return AgentConfig.model_validate(yaml.safe_load(substitute(text, kb_ids)) or {})


def parse_workflow(text: str, kb_ids: dict[str, str]) -> WorkflowConfig:
    return WorkflowConfig.model_validate(yaml.safe_load(substitute(text, kb_ids)) or {})


def read_table_rows(template: LoadedTemplate, table: TableSpec) -> list[dict[str, Any]]:
    """Rows of a sample CSV as strings keyed by column (typing happens in the knowledge base loader)."""
    raw = (template.root / table.source).read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(raw))
    return [{k: (v if v != "" else None) for k, v in row.items() if k is not None} for row in reader]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_members(root: Path, problems: list[str]) -> list[MemberFiles]:
    base = root / "workforce"
    members: list[MemberFiles] = []
    if not base.is_dir():
        return members
    for member_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        agent_file, workflow_file = member_dir / AGENT_FILE, member_dir / WORKFLOW_FILE
        if agent_file.is_file() == workflow_file.is_file():
            problems.append(f"workforce/{member_dir.name}: needs exactly one of {AGENT_FILE} or {WORKFLOW_FILE}")
            continue
        kind: Literal["agent", "workflow"] = "agent" if agent_file.is_file() else "workflow"
        member = MemberFiles(
            name=member_dir.name, kind=kind, config_text=_read(agent_file if kind == "agent" else workflow_file)
        )
        for extra in (TOOLS_FILE, CUSTOM_NODES_FILE):
            if (member_dir / extra).is_file():
                member.extra[extra] = _read(member_dir / extra)
        evals_dir = member_dir / "evals"
        if evals_dir.is_dir():
            for eval_file in sorted(evals_dir.glob("*.yaml")):
                member.evals[f"evals/{eval_file.name}"] = _read(eval_file)
        members.append(member)
    return members


def _check_evals(member: MemberFiles, kb_ids: dict[str, str], problems: list[str]) -> list[dict[str, Any]]:
    """Every eval case: runnable, unique name, offline or llm tag (llm cases need a judge validator)."""
    cases: list[dict[str, Any]] = []
    expected_runnable = "_member.py::agent" if member.kind == "agent" else "../workflow.py::workflow"
    for path, text in member.evals.items():
        try:
            data = yaml.safe_load(substitute(text, kb_ids))
        except (yaml.YAMLError, KeyError) as exc:
            problems.append(f"{member.name}/{path}: invalid YAML ({exc})")
            continue
        if not isinstance(data, list) or not data:
            problems.append(f"{member.name}/{path}: must be a non-empty list of evals")
            continue
        for case in data:
            if not isinstance(case, dict) or not case.get("name"):
                problems.append(f"{member.name}/{path}: every eval needs a name")
                continue
            tags = [str(t) for t in case.get("tags") or []]
            if case.get("runnable") != expected_runnable:
                problems.append(f"{member.name}/{case['name']}: runnable must be {expected_runnable}")
            if (OFFLINE_EVAL_TAG in tags) == (LLM_EVAL_TAG in tags):
                problems.append(f"{member.name}/{case['name']}: tag it either {OFFLINE_EVAL_TAG} or {LLM_EVAL_TAG}")
            if LLM_EVAL_TAG in tags and "rubric!" not in json.dumps(case):
                problems.append(f"{member.name}/{case['name']}: llm evals must use an LLM judge (rubric!)")
            cases.append(
                {
                    "member": member.name,
                    "name": str(case["name"]),
                    "description": str(case.get("description") or ""),
                    "tags": tags,
                }
            )
    names = [c["name"] for c in cases]
    if len(names) != len(set(names)):
        problems.append(f"{member.name}: eval names must be unique")
    if not any(OFFLINE_EVAL_TAG in c["tags"] for c in cases):
        problems.append(f"{member.name}: needs at least one {OFFLINE_EVAL_TAG} eval")
    return cases


def _check_documents(root: Path, manifest: TemplateManifest, problems: list[str]) -> None:
    for kb in manifest.knowledge_bases:
        for doc in kb.documents:
            if not (root / doc.source).is_file():
                problems.append(f"knowledge {kb.key}: missing {doc.source}")
        for table in kb.tables:
            path = root / table.source
            if not path.is_file():
                problems.append(f"knowledge {kb.key}: missing {table.source}")
                continue
            header = next(csv.reader(io.StringIO(path.read_text(encoding="utf-8"))), [])
            declared = [c.name for c in table.columns]
            if header != declared:
                problems.append(f"{table.source}: header {header} does not match the declared columns {declared}")


def _tool_label(tool: Any) -> str:
    if tool.type == "builtin":
        return str(BUILTIN_TOOLS.get(tool.key, {}).get("label", tool.key))
    return tool.description or tool.name or tool.key


def _summarize(
    manifest: TemplateManifest,
    agents: dict[str, AgentConfig],
    workflows: dict[str, WorkflowConfig],
    interfaces: dict[str, Any],
    evals: list[dict[str, Any]],
    plan: Plan,
    row_counts: dict[str, int],
) -> dict[str, Any]:
    kb_by_id = {v: k for k, v in stand_in_kb_ids(manifest).items()}
    return {
        "version": manifest.version,
        "includes": manifest.includes,
        "includes_en": manifest.includes_en,
        "default_model_tier": manifest.default_model_tier,
        "agents": [
            {
                "name": cfg.name,
                "description": cfg.description,
                "tools": [
                    {
                        "key": t.key,
                        "type": t.type,
                        "label": _tool_label(t),
                        "requires_approval": t.requires_approval or bool(t.config.get("approval_threshold_eur")),
                        "approval_threshold_eur": t.config.get("approval_threshold_eur"),
                    }
                    for t in cfg.tools
                ],
                "knowledge_bases": [kb_by_id.get(k, k) for k in cfg.knowledge_bases],
                "voice": cfg.voice.enabled,
                "greeting": cfg.voice.greeting,
                "model_tier": cfg.model_tier,
            }
            for cfg in agents.values()
        ],
        "workflows": [
            {
                "name": cfg.name,
                "description": cfg.description,
                "inputs": [i.model_dump(mode="json") for i in cfg.inputs],
                "steps": [{"id": n.id, "type": n.type, "label": n.label} for n in cfg.nodes],
                "approvals": [n.label or n.id for n in cfg.nodes if n.type == "approval"],
            }
            for cfg in workflows.values()
        ],
        "knowledge_bases": [
            {
                "key": kb.key,
                "name": kb.name,
                "name_en": kb.name_en,
                "description": kb.description,
                "description_en": kb.description_en,
                "documents": [{"filename": d.filename, "title": d.title} for d in kb.documents],
                "tables": [
                    {
                        "name": t.name,
                        "description": t.description,
                        "columns": [c.name for c in t.columns],
                        "rows": row_counts.get(f"{kb.key}.{t.name}", 0),
                    }
                    for t in kb.tables
                ],
            }
            for kb in manifest.knowledge_bases
        ],
        "interfaces": [
            {
                "slug": spec.slug,
                "name": spec.name,
                "kind": spec.kind,
                "description": spec.description,
                "screens": [{"title": s.title, "components": [c.type for c in s.components]} for s in spec.screens],
            }
            for spec in interfaces.values()
        ],
        "channels": [c.model_dump(mode="json") for c in manifest.channels],
        "phone": manifest.phone.model_dump(mode="json") if manifest.phone else None,
        "triggers": [
            {
                "member": t.member,
                "kind": t.kind,
                "name": t.name,
                "description": t.description,
                "enabled": t.enabled,
                "schedule": t.config.get("expression"),
            }
            for t in manifest.triggers
        ],
        "requirements": [r.model_dump(mode="json") for r in manifest.requirements],
        "evals": evals,
        "try_prompts": [p.model_dump(mode="json") for p in manifest.try_prompts],
        "plan": {"goal": plan.goal, "summary": plan.summary, "risks": plan.risks},
    }


def load_template_dir(root: Path) -> LoadedTemplate:
    """Load and validate one template directory. Raises :class:`TemplateError` listing every problem."""
    template_id = root.name
    problems: list[str] = []
    try:
        manifest = TemplateManifest.model_validate(yaml.safe_load(_read(root / TEMPLATE_FILE)) or {})
    except FileNotFoundError as exc:
        raise TemplateError(template_id, [f"missing {TEMPLATE_FILE}"]) from exc
    except (ValidationError, yaml.YAMLError) as exc:
        raise TemplateError(template_id, [f"{TEMPLATE_FILE}: {exc}"]) from exc
    if manifest.id != template_id:
        problems.append(f"manifest id {manifest.id!r} must match the directory name")
    try:
        plan_data = json.loads(_read(root / PLAN_FILE))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise TemplateError(template_id, [f"{PLAN_FILE}: {exc}"]) from exc
    plan, plan_issues = validate_plan(plan_data)
    problems += [f"{PLAN_FILE}: {i}" for i in plan_issues]
    if plan is not None and plan.template_id not in (None, manifest.id):
        problems.append(f"{PLAN_FILE}: template_id must be {manifest.id}")
    readme = _read(root / README_FILE) if (root / README_FILE).is_file() else ""
    if not readme.strip():
        problems.append(f"missing {README_FILE}")
    _check_documents(root, manifest, problems)

    kb_ids = stand_in_kb_ids(manifest)
    members = _load_members(root, problems)
    agents: dict[str, AgentConfig] = {}
    workflows: dict[str, WorkflowConfig] = {}
    for m in members:
        try:
            if m.kind == "agent":
                cfg = parse_agent(m.config_text, kb_ids)
                agents[m.name] = cfg
                if cfg.name != m.name:
                    problems.append(f"workforce/{m.name}: config name {cfg.name!r} must match the directory")
                if any(t.type == "custom" for t in cfg.tools) and TOOLS_FILE not in m.extra:
                    problems.append(f"workforce/{m.name}: custom tools need {TOOLS_FILE}")
            else:
                workflows[m.name] = parse_workflow(m.config_text, kb_ids)
                if workflows[m.name].name != m.name:
                    problems.append(f"workforce/{m.name}: config name must match the directory")
        except (ValidationError, yaml.YAMLError, KeyError) as exc:
            problems.append(f"workforce/{m.name}: {exc}")
    kinds = {m.name: m.kind for m in members}
    for name, wf in workflows.items():
        member = next(m for m in members if m.name == name)
        try:
            functions = [f.name for f in parse_custom_nodes(member.extra.get(CUSTOM_NODES_FILE, ""))]
        except SyntaxError as exc:
            problems.append(f"workforce/{name}/{CUSTOM_NODES_FILE}: {exc}")
            continue
        issues = validate_workflow(
            wf, members={k: v for k, v in kinds.items() if k != name}, custom_functions=functions
        )
        problems += [f"workforce/{name}: {i['message']} ({i.get('node_id', '')})" for i in issues]
    for m in members:
        source = m.extra.get(TOOLS_FILE)
        if source is not None:
            try:
                compile(substitute(source, kb_ids), f"{m.name}/{TOOLS_FILE}", "exec")
            except (SyntaxError, KeyError) as exc:
                problems.append(f"workforce/{m.name}/{TOOLS_FILE}: {exc}")
    evals: list[dict[str, Any]] = []
    for m in members:
        evals += _check_evals(m, kb_ids, problems)

    interfaces_text: dict[str, str] = {}
    interfaces: dict[str, Any] = {}
    base = root / "interfaces"
    for path in sorted(base.glob(f"*/{INTERFACE_FILE}")) if base.is_dir() else []:
        slug = path.parent.name
        text = _read(path)
        try:
            spec = validate_interface(json.loads(substitute(text, kb_ids)))
        except (InterfaceValidationError, json.JSONDecodeError, KeyError) as exc:
            problems.append(f"interfaces/{slug}: {exc}")
            continue
        if spec.slug != slug:
            problems.append(f"interfaces/{slug}: slug must match the directory")
        missing = sorted(spec.workforce_names() - set(kinds))
        if missing:
            problems.append(f"interfaces/{slug}: unknown workforce {', '.join(missing)}")
        interfaces_text[slug], interfaces[slug] = text, spec

    for channel in manifest.channels:
        if kinds.get(channel.agent) != "agent":
            problems.append(f"channel {channel.provider}: {channel.agent} is not an agent of the template")
    if manifest.phone and kinds.get(manifest.phone.agent) != "agent":
        problems.append(f"phone: {manifest.phone.agent} is not an agent of the template")
    if manifest.phone and not agents.get(manifest.phone.agent, AgentConfig(name="x")).voice.enabled:
        problems.append(f"phone: {manifest.phone.agent} must have voice enabled")
    for trigger in manifest.triggers:
        if trigger.member not in kinds:
            problems.append(f"trigger {trigger.name}: unknown member {trigger.member}")
        if trigger.kind == "file" and str(trigger.config.get("kb_id", "")).removeprefix("${kb:").rstrip("}") not in {
            k.key for k in manifest.knowledge_bases
        }:
            problems.append(f"trigger {trigger.name}: file triggers need kb_id: ${{kb:<key>}}")
    for prompt in manifest.try_prompts:
        if prompt.member not in kinds:
            problems.append(f"try_prompts: unknown member {prompt.member}")
    if not members:
        problems.append("a template needs at least one agent or workflow")
    if not interfaces:
        problems.append("a template needs an interface")
    if not manifest.knowledge_bases:
        problems.append("a template needs a sample knowledge base")
    if plan is not None:
        plan_members = {a.name for a in plan.agents} | {w.name for w in plan.workflows}
        if plan_members != set(kinds):
            problems.append(f"{PLAN_FILE}: members {sorted(plan_members)} must match the template {sorted(kinds)}")
    if problems or plan is None:
        raise TemplateError(template_id, problems or ["invalid plan"])

    row_counts: dict[str, int] = {}
    loaded = LoadedTemplate(
        root=root,
        manifest=manifest,
        plan=plan,
        readme=readme,
        members=members,
        interfaces=interfaces_text,
        summary={},
    )
    for kb in manifest.knowledge_bases:
        for table in kb.tables:
            row_counts[f"{kb.key}.{table.name}"] = len(read_table_rows(loaded, table))
    loaded.summary = _summarize(manifest, agents, workflows, interfaces, evals, plan, row_counts)
    return loaded


@dataclass(slots=True)
class _Catalog:
    templates: tuple[LoadedTemplate, ...]
    errors: dict[str, list[str]]


@lru_cache(maxsize=1)
def _catalog(root: str) -> _Catalog:
    base = Path(root)
    loaded: list[LoadedTemplate] = []
    errors: dict[str, list[str]] = {}
    if base.is_dir():
        for path in sorted(base.iterdir()):
            if not (path / TEMPLATE_FILE).is_file():
                continue
            try:
                loaded.append(load_template_dir(path))
            except TemplateError as exc:
                errors[exc.template_id] = exc.problems
                log.error("templates.invalid", template=exc.template_id, problems=exc.problems[:10])
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                errors[path.name] = [str(exc)]
                log.error("templates.unreadable", template=path.name, error=str(exc)[:300])
    return _Catalog(tuple(sorted(loaded, key=lambda t: (t.manifest.sort_order, t.id))), errors)


def all_templates() -> list[LoadedTemplate]:
    """Every valid template on disk (cached for the life of the process). Invalid ones are skipped and logged,
    so a broken template never breaks seeding or the API; :func:`load_errors` lists them (tests assert none)."""
    return list(_catalog(str(templates_dir())).templates)


def load_errors() -> dict[str, list[str]]:
    """Problems of the template directories that could not be loaded (template id → problems)."""
    return dict(_catalog(str(templates_dir())).errors)


def get_template(template_id: str) -> LoadedTemplate | None:
    return next((t for t in all_templates() if t.id == template_id), None)


def reset_cache() -> None:
    _catalog.cache_clear()


# ================================================================================================ seeding


async def seed_templates(session: AsyncSession) -> None:
    """Upsert the catalog rows from the template directories (idempotent).

    Content columns follow the files; ``public`` and ``sort_order`` are set only on first insert because the
    backoffice owns them afterwards.
    """
    for template in all_templates():
        m = template.manifest
        content = {
            "sector": m.sector,
            "name": m.name,
            "name_en": m.name_en,
            "description": m.description,
            "description_en": m.description_en,
            "repo_snapshot": f"packages/templates/{m.id}",
            "tags": list(m.tags),
            "manifest": template.summary,
        }
        await session.execute(
            insert(Template)
            .values(id=m.id, public=True, sort_order=m.sort_order, **content)
            .on_conflict_do_update(index_elements=[Template.id], set_=content)
        )
    log.info("templates.seeded", count=len(all_templates()))


async def catalog_rows(session: AsyncSession, *, include_private: bool = False) -> list[Template]:
    """Catalog rows that have a template directory, in display order."""
    known = {t.id for t in all_templates()}
    q = select(Template).order_by(Template.sort_order, Template.name)
    if not include_private:
        q = q.where(Template.public.is_(True))
    return [row for row in (await session.execute(q)).scalars().all() if row.id in known]


# ================================================================================================ matching


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return " " + re.sub(r"[^a-z0-9€]+", " ", "".join(c for c in text if not unicodedata.combining(c))) + " "


def _weighted_keywords(manifest: TemplateManifest) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for raw in manifest.keywords:
        term, _, weight = raw.rpartition(":")
        if not term:
            term, weight = weight, "1"
        try:
            out.append((_normalize(term).strip(), float(weight)))
        except ValueError:
            out.append((_normalize(raw).strip(), 1.0))
    return out


def match_scores(text: str) -> list[tuple[str, float]]:
    """Score of every template for a free-text request (highest first)."""
    haystack = _normalize(text)
    scores: list[tuple[str, float]] = []
    for template in all_templates():
        score = 0.0
        for term, weight in _weighted_keywords(template.manifest):
            if term and f" {term}" in haystack:
                score += weight
        scores.append((template.id, score))
    return sorted(scores, key=lambda s: s[1], reverse=True)


MATCH_THRESHOLD = 4.0


def match_template(text: str) -> str | None:
    """The template that best fits a request (keyword and sector match, Spanish or English), or ``None``.

    Used by the Composer's offline mode. A match needs a clear signal (``MATCH_THRESHOLD``) and a margin over
    the runner-up so ambiguous requests are not forced into a template.
    """
    scores = match_scores(text)
    if not scores or scores[0][1] < MATCH_THRESHOLD:
        return None
    if len(scores) > 1 and scores[0][1] - scores[1][1] < 1.0:
        return None
    return scores[0][0]
