"""Interfaces: generated apps, dashboards and public chats (spec 7.8).

Everything is code: an interface is ``interfaces/<slug>/interface.json`` in the project repository and every
change is a commit; the ``interfaces`` table only indexes those files (draft = HEAD) and keeps the
``published_definition`` snapshotted by :func:`publish_for_deployment` when a version goes live in production.

Execution of bindings:

* ``knowledge_sql``    → :func:`messer_common.knowledge.sql.run_readonly` (read-only role, the user's policies,
                         values only as ``$n`` parameters);
* ``knowledge_search`` → :func:`messer_common.knowledge.search.search`;
* ``agent`` / ``workflow`` → the runtime (development = HEAD for the Studio preview, production = the deployed
                         version for public pages; runs are traced and charged to the organization);
* ``approvals``        → the project's approvals (decisions reuse the approvals API);
* ``file_upload``      → :func:`messer_api.services.knowledge.ingest_bytes`.

Public pages identify anonymous end users with a signed, httpOnly cookie; their conversations live in
``conversations`` (``channel_key = "public-chat:<interface>"``, ``external_user_id = "anon:<id>"``).
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit, runtime_client
from messer_common.db import Principal, system_session
from messer_common.db.models import (
    Approval,
    AuditLog,
    Conversation,
    Environment,
    Interface,
    KnowledgeBase,
    Membership,
    Org,
    Project,
    Run,
    Workforce,
)
from messer_common.execution import NotDeployed, resolve_target
from messer_common.interfaces import (
    INTERFACES_DIR,
    AnyComponent,
    InterfaceSpec,
    InterfaceValidationError,
    ValidationIssue,
    build_template,
    check_interface,
    interface_path,
    template_info,
    validate_interface,
)
from messer_common.interfaces.resolve import (
    BindingInputError,
    RequestContext,
    clean_values,
    default_prompt,
    form_values,
    render_prompt,
    sql_params,
    workflow_input,
)
from messer_common.interfaces.spec import (
    SLUG_PATTERN,
    ActionButtonComponent,
    AgentBinding,
    ApprovalsBinding,
    ApprovalsInboxComponent,
    ChatComponent,
    Component,
    DataTableComponent,
    FileUploadComponent,
    FormComponent,
    KnowledgeSearchBinding,
    KnowledgeSqlBinding,
    RecordListComponent,
    StaticBinding,
    WorkflowBinding,
)
from messer_common.interfaces.validation import issues_from_pydantic, semantic_issues
from messer_common.knowledge.errors import KnowledgeError
from messer_common.knowledge.search import search as kb_search
from messer_common.knowledge.sql import run_readonly
from messer_common.logging import get_logger
from messer_common.projects_repo import Commit, ProjectRepo, RepoError
from messer_common.roles import at_least
from messer_common.runtime_client import RuntimeUnavailable
from messer_common.security import TokenError, random_token, sign_payload, verify_signed_payload
from messer_common.settings import get_settings

from ..deps import org_billing_state
from ..errors import ApiError, Conflict, Forbidden, NotFound, PaymentRequired, Unauthorized
from . import projects as project_svc

log = get_logger("messer.interfaces")

Environment_ = Literal["development", "production"]
END_USER_COOKIE = "messer_eu"
END_USER_HEADER = "x-messer-end-user"
END_USER_PURPOSE = "end_user"
END_USER_TTL_S = 365 * 24 * 3600
PUBLIC_CHAT_CHANNEL = "public_chat"
INTERFACE_CHANNEL = "interface"
_component_adapter: TypeAdapter[Any] = TypeAdapter(Component)
_SLUG_RE = re.compile(SLUG_PATTERN)


# ================================================================================================ errors


class InterfaceInvalid(ApiError):
    status_code = 422
    code = "interface_invalid"

    def __init__(self, issues: list[ValidationIssue], message: str | None = None) -> None:
        super().__init__(
            message or (issues[0].message if len(issues) == 1 else f"La interfaz tiene {len(issues)} errores"),
            details={"issues": [i.to_dict() for i in issues]},
        )


def _invalid(exc: InterfaceValidationError) -> InterfaceInvalid:
    return InterfaceInvalid(exc.issues)


def knowledge_api_error(exc: KnowledgeError) -> ApiError:
    if exc.status == 404:
        return NotFound(exc.message, code=exc.code, details=exc.details)
    return ApiError(exc.message, code=exc.code, status_code=exc.status, details=exc.details)


def _input_error(exc: BindingInputError) -> ApiError:
    return ApiError(exc.message, code="invalid_input", status_code=422, details={"field": exc.field_name})


async def record_audit(session: AsyncSession, **kwargs: Any) -> None:
    """``audit.record`` with a client-side timestamp, so members who cannot read the audit log can insert.

    Without it the INSERT uses ``RETURNING created_at``, which row level security refuses for non-admins.
    """
    await audit.record(session, **kwargs)
    now = datetime.now(UTC)
    for obj in session.new:
        if isinstance(obj, AuditLog) and obj.created_at is None:
            obj.created_at = now


# ================================================================================================ repository


def repo_for(project: Project) -> ProjectRepo:
    return ProjectRepo.for_project(str(project.id))


def dump_definition(spec: InterfaceSpec) -> str:
    return json.dumps(spec.to_json(), ensure_ascii=False, indent=2) + "\n"


def _slug_from_path(path: str) -> str | None:
    parts = path.split("/")
    if len(parts) == 3 and parts[0] == INTERFACES_DIR and parts[2] == "interface.json" and _SLUG_RE.match(parts[1]):
        return parts[1]
    return None


async def interface_files(repo: ProjectRepo, ref: str = "HEAD") -> dict[str, str]:
    """slug → path of every ``interfaces/<slug>/interface.json`` at ``ref``."""
    try:
        files = await repo.list_files(ref, prefix=f"{INTERFACES_DIR}/")
    except RepoError:
        return {}
    out: dict[str, str] = {}
    for path in files:
        slug = _slug_from_path(path)
        if slug:
            out[slug] = path
    return out


def _parse_raw(text: str | None) -> dict[str, Any] | None:
    if text is None:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _columns_from_spec(spec: InterfaceSpec) -> dict[str, Any]:
    return {
        "name": spec.name,
        "kind": spec.kind,
        "public": not spec.requires_login,
        "auth_required": spec.requires_login,
        "workforce_name": spec.chat_agent,
        "theme": spec.theme.model_dump(mode="json"),
    }


async def sync_index(project: Project) -> None:
    """Index the interfaces at HEAD (files written by git pushes, the Composer or by hand)."""
    files = await interface_files(repo_for(project))
    repo = repo_for(project)
    async with system_session() as s:
        rows = {
            r.slug: r
            for r in (await s.execute(select(Interface).where(Interface.project_id == project.id))).scalars().all()
        }
        for slug, path in files.items():
            raw = _parse_raw(await repo.read(path))
            spec, _ = check_interface(raw) if raw is not None else (None, [])
            row = rows.get(slug)
            if row is None:
                values: dict[str, Any] = {
                    "id": uuid.uuid4(),
                    "org_id": project.org_id,
                    "project_id": project.id,
                    "slug": slug,
                    "definition": raw or {},
                    **(
                        _columns_from_spec(spec)
                        if spec is not None
                        else {"name": str((raw or {}).get("name") or slug)[:200], "kind": "app"}
                    ),
                }
                await s.execute(pg_insert(Interface).values(**values).on_conflict_do_nothing())
                continue
            if raw is not None and raw != row.definition:
                row.definition = raw
                if spec is not None:
                    for key, value in _columns_from_spec(spec).items():
                        setattr(row, key, value)
        for slug, row in rows.items():
            if slug not in files and row.published_definition is None:
                await s.delete(row)


# ================================================================================================ CRUD


@dataclass(slots=True)
class InterfaceState:
    row: Interface
    definition: dict[str, Any]
    spec: InterfaceSpec | None
    issues: list[ValidationIssue]
    commit: str | None


async def load_state(project: Project, row: Interface, ref: str = "HEAD") -> InterfaceState:
    repo = repo_for(project)
    path = interface_path(row.slug)
    text = await repo.read(path, ref)
    raw = _parse_raw(text)
    if text is not None and raw is None:
        issues = [ValidationIssue("$", "invalid_json", "El archivo interface.json no es un objeto JSON válido")]
        return InterfaceState(row, row.definition or {}, None, issues, await _last_commit(repo, path))
    definition = raw if raw is not None else (row.definition or {})
    spec, issues = check_interface(definition)
    return InterfaceState(row, definition, spec, issues, await _last_commit(repo, path) if text is not None else None)


async def _last_commit(repo: ProjectRepo, path: str) -> str | None:
    try:
        commits = await repo.log(path, limit=1)
    except RepoError:
        return None
    return commits[0].sha if commits else None


async def get_row(session: AsyncSession, principal: Principal, interface_id: uuid.UUID) -> Interface:
    row = await session.get(Interface, interface_id)
    if row is None or row.org_id != principal.org_id:
        raise NotFound("Interfaz no encontrada")
    if principal.project_id is not None and principal.project_id != row.project_id:
        raise Forbidden("La API key está limitada a otro proyecto", code="project_scope")
    return row


async def unique_slug(session: AsyncSession, project: Project, base: str) -> str:
    from slugify import slugify

    root = slugify(base, max_length=60) or "interfaz"
    taken = set((await session.execute(select(Interface.slug).where(Interface.project_id == project.id))).scalars())
    taken |= set(await interface_files(repo_for(project)))
    slug, n = root, 2
    while slug in taken:
        slug = f"{root}-{n}"
        n += 1
    return slug


async def reference_warnings(project: Project, spec: InterfaceSpec) -> list[ValidationIssue]:
    """Knowledge bases and workforce members the interface uses that do not exist (yet) in the project."""
    warnings: list[ValidationIssue] = []
    kb_ids = spec.knowledge_base_ids()
    names = spec.workforce_names()
    async with system_session() as s:
        kbs = (
            {kb.id: kb for kb in (await s.execute(select(KnowledgeBase).where(KnowledgeBase.id.in_(kb_ids)))).scalars()}
            if kb_ids
            else {}
        )
        members = (
            {
                m.name: m.kind
                for m in (
                    await s.execute(
                        select(Workforce).where(Workforce.project_id == project.id, Workforce.name.in_(names))
                    )
                ).scalars()
            }
            if names
            else {}
        )
    for si, screen in enumerate(spec.screens):
        for ci, comp in enumerate(screen.components):
            base = f"screens[{si}].components[{ci}]"
            for path, kb_id in _component_kbs(comp, base):
                kb = kbs.get(kb_id)
                if kb is None or kb.org_id != project.org_id:
                    warnings.append(ValidationIssue(path, "kb_not_found", f"La base de conocimiento {kb_id} no existe"))
                elif kb.project_id is not None and kb.project_id != project.id:
                    warnings.append(ValidationIssue(path, "kb_other_project", f"«{kb.name}» pertenece a otro proyecto"))
            for path, binding in _component_runs(comp, base):
                kind = members.get(binding.workforce)
                expected = "agent" if isinstance(binding, AgentBinding) else "workflow"
                if kind is None:
                    warnings.append(
                        ValidationIssue(f"{path}.workforce", "workforce_not_found", f"«{binding.workforce}» no existe")
                    )
                elif kind != expected:
                    warnings.append(
                        ValidationIssue(
                            f"{path}.workforce",
                            "workforce_kind",
                            f"«{binding.workforce}» es un {'agente' if kind == 'agent' else 'flujo'}, no un "
                            f"{'agente' if expected == 'agent' else 'flujo'}",
                        )
                    )
            if isinstance(comp.binding, ApprovalsBinding) and comp.binding.project not in ("current", str(project.id)):
                warnings.append(
                    ValidationIssue(
                        f"{base}.binding.project", "approvals_project", "Solo se muestran aprobaciones de este proyecto"
                    )
                )
    return warnings


def _component_kbs(comp: AnyComponent, base: str) -> list[tuple[str, uuid.UUID]]:
    out: list[tuple[str, uuid.UUID]] = []
    if isinstance(comp.binding, KnowledgeSqlBinding):
        out.append((f"{base}.binding.kb_id", comp.binding.kb_id))
    elif isinstance(comp.binding, KnowledgeSearchBinding):
        out.extend((f"{base}.binding.kb_ids[{i}]", kb) for i, kb in enumerate(comp.binding.kb_ids))
    if isinstance(comp, FileUploadComponent):
        out.append((f"{base}.props.kb_id", comp.props.kb_id))
    return out


def _component_runs(comp: AnyComponent, base: str) -> list[tuple[str, AgentBinding | WorkflowBinding]]:
    out: list[tuple[str, AgentBinding | WorkflowBinding]] = []
    if isinstance(comp.binding, AgentBinding | WorkflowBinding):
        out.append((f"{base}.binding", comp.binding))
    if isinstance(comp, DataTableComponent | RecordListComponent) and comp.props.row_action is not None:
        out.append((f"{base}.props.row_action.binding", comp.props.row_action.binding))
    return out


async def create_interface(
    session: AsyncSession,
    principal: Principal,
    project: Project,
    *,
    definition: dict[str, Any],
    message: str | None = None,
) -> tuple[Interface, str]:
    try:
        spec = validate_interface(definition)
    except InterfaceValidationError as exc:
        raise _invalid(exc) from exc
    taken = (
        await session.execute(
            select(Interface.id).where(Interface.project_id == project.id, Interface.slug == spec.slug)
        )
    ).first()
    if taken is not None or spec.slug in await interface_files(repo_for(project)):
        raise Conflict(f"Ya existe una interfaz con el identificador «{spec.slug}»", code="slug_taken")
    author = await project_svc.author_for(session, principal)
    commit = await repo_for(project).write(
        {interface_path(spec.slug): dump_definition(spec)},
        message=message or f"Add interface {spec.name}",
        author=author.name,
        email=author.email,
    )
    row = Interface(
        org_id=project.org_id,
        project_id=project.id,
        slug=spec.slug,
        definition=spec.to_json(),
        **_columns_from_spec(spec),
    )
    session.add(row)
    await session.flush()
    await record_audit(
        session,
        action="interface.created",
        principal=principal,
        entity_type="interface",
        entity_id=row.id,
        diff={"slug": spec.slug, "kind": spec.kind, "commit": commit},
    )
    return row, commit


async def definition_from_template(
    session: AsyncSession,
    project: Project,
    *,
    template: str,
    name: str,
    slug: str | None,
    kb_id: uuid.UUID | None,
    table: str | None,
    agent: str | None,
) -> dict[str, Any]:
    info = template_info(template)
    if info is None:
        raise ApiError(f"Plantilla desconocida «{template}»", code="unknown_template")
    final_slug = slug or await unique_slug(session, project, name)
    columns: list[dict[str, Any]] | None = None
    if kb_id is not None:
        kb = await _kb_for(project, kb_id)
        if table is not None:
            columns = await _table_columns(kb, table)
    try:
        return build_template(
            template, name=name, slug=final_slug, kb_id=kb_id, table=table, columns=columns, agent=agent
        )
    except ValueError as exc:
        raise ApiError(str(exc), code="template_params", status_code=422) from exc


async def _table_columns(kb: KnowledgeBase, table: str) -> list[dict[str, Any]]:
    from messer_common.db.models import KbTable

    async with system_session() as s:
        row = (
            await s.execute(select(KbTable).where(KbTable.kb_id == kb.id, KbTable.name == table))
        ).scalar_one_or_none()
    if row is None:
        raise NotFound(f"La tabla «{table}» no existe en «{kb.name}»", code="table_not_found")
    return [
        {"name": str(c.get("name")), "type": str(c.get("type") or "text")}
        for c in (row.schema_json or {}).get("columns", [])
        if c.get("name")
    ]


async def update_interface(
    session: AsyncSession,
    principal: Principal,
    project: Project,
    row: Interface,
    *,
    definition: dict[str, Any],
    message: str | None = None,
) -> str:
    try:
        spec = validate_interface(definition)
    except InterfaceValidationError as exc:
        raise _invalid(exc) from exc
    files: dict[str, str | bytes | None] = {interface_path(spec.slug): dump_definition(spec)}
    old_slug = row.slug
    if spec.slug != old_slug:
        taken = (
            await session.execute(
                select(Interface.id).where(
                    Interface.project_id == project.id, Interface.slug == spec.slug, Interface.id != row.id
                )
            )
        ).first()
        if taken is not None or spec.slug in await interface_files(repo_for(project)):
            raise Conflict(f"Ya existe una interfaz con el identificador «{spec.slug}»", code="slug_taken")
        files[interface_path(old_slug)] = None
    author = await project_svc.author_for(session, principal)
    commit = await repo_for(project).write(
        files, message=message or f"Update interface {spec.name}", author=author.name, email=author.email
    )
    row.slug = spec.slug
    row.definition = spec.to_json()
    for key, value in _columns_from_spec(spec).items():
        setattr(row, key, value)
    row.updated_at = datetime.now(UTC)
    await record_audit(
        session,
        action="interface.updated",
        principal=principal,
        entity_type="interface",
        entity_id=row.id,
        diff={"slug": spec.slug, "renamed_from": old_slug if old_slug != spec.slug else None, "commit": commit},
    )
    return commit


async def delete_interface(session: AsyncSession, principal: Principal, project: Project, row: Interface) -> str:
    author = await project_svc.author_for(session, principal)
    commit = await repo_for(project).write(
        {interface_path(row.slug): None},
        message=f"Remove interface {row.name}",
        author=author.name,
        email=author.email,
    )
    await record_audit(
        session,
        action="interface.deleted",
        principal=principal,
        entity_type="interface",
        entity_id=row.id,
        diff={"slug": row.slug, "was_published": row.published_definition is not None, "commit": commit},
    )
    await session.delete(row)
    return commit


async def versions(project: Project, row: Interface, limit: int = 50) -> list[Commit]:
    try:
        return await repo_for(project).log(interface_path(row.slug), limit=limit)
    except RepoError:
        return []


async def definition_at(project: Project, row: Interface, sha: str) -> dict[str, Any]:
    repo = repo_for(project)
    try:
        commit = await repo.resolve(sha)
    except RepoError as exc:
        raise NotFound("Versión no encontrada", code="version_not_found") from exc
    raw = _parse_raw(await repo.read(interface_path(row.slug), commit))
    if raw is None:
        raise NotFound("La interfaz no existía en esa versión", code="version_not_found")
    return raw


async def restore_version(
    session: AsyncSession, principal: Principal, project: Project, row: Interface, sha: str
) -> str:
    definition = await definition_at(project, row, sha)
    definition["slug"] = row.slug
    return await update_interface(
        session, principal, project, row, definition=definition, message=f"Restore interface {row.name} to {sha[:8]}"
    )


def public_urls(org: Org, project: Project, row: Interface, spec: InterfaceSpec | None) -> dict[str, str | None]:
    web = get_settings().messer_web_url.rstrip("/")
    base = f"{web}/{org.slug}/{project.slug}"
    agent = (spec.chat_agent if spec else None) or row.workforce_name
    if row.kind == "chat" and agent:
        embed = f"{web}/embed/{org.slug}/{project.slug}/chat/{agent}"
        snippet = (
            f'<script src="{web}/widget/v1.js" data-project="{org.slug}/{project.slug}" '
            f'data-agent="{agent}" async></script>'
        )
        return {"public": f"{base}/chat/{agent}", "embed": embed, "widget": snippet}
    return {"public": f"{base}/app/{row.slug}", "embed": None, "widget": None}


# ================================================================================================ actors


@dataclass(slots=True)
class Actor:
    """Who is using an interface: an organization member (Studio or logged-in public page) or an end user."""

    org_id: uuid.UUID
    user_id: uuid.UUID | None = None
    email: str | None = None
    role: str | None = None  # organization role (None for anonymous end users)
    is_superadmin: bool = False
    api_key_id: uuid.UUID | None = None
    end_user: str | None = None  # conversation identity: "user:<id>" or "anon:<id>"
    new_end_user_token: str | None = None  # set when a fresh anonymous identity was issued

    @property
    def is_member(self) -> bool:
        return self.role is not None or self.is_superadmin

    @property
    def policy_role(self) -> str:
        """Knowledge policies to apply: the member's role; anonymous visitors get the viewer's policies."""
        return self.role or "viewer"

    def principal(self) -> Principal:
        return Principal(
            user_id=self.user_id,
            org_id=self.org_id,
            role=self.role,
            is_superadmin=self.is_superadmin,
            email=self.email,
            api_key_id=self.api_key_id,
        )

    def context(self, **kwargs: Any) -> RequestContext:
        return RequestContext(user_id=str(self.user_id) if self.user_id else None, user_email=self.email, **kwargs)


def actor_from_principal(principal: Principal) -> Actor:
    assert principal.org_id is not None
    return Actor(
        org_id=principal.org_id,
        user_id=principal.user_id,
        email=principal.email,
        role=principal.role or ("owner" if principal.is_superadmin else None),
        is_superadmin=principal.is_superadmin,
        api_key_id=principal.api_key_id,
        end_user=f"user:{principal.user_id}" if principal.user_id else None,
    )


def end_user_token(end_user: str) -> str:
    return sign_payload({"purpose": END_USER_PURPOSE, "sub": end_user}, ttl_s=END_USER_TTL_S)


def issue_end_user_token() -> tuple[str, str]:
    end_user = random_token(18)
    return end_user, end_user_token(end_user)


def read_end_user_token(token: str | None) -> str | None:
    if not token:
        return None
    try:
        payload = verify_signed_payload(token)
    except TokenError:
        return None
    sub = payload.get("sub")
    if payload.get("purpose") != END_USER_PURPOSE or not isinstance(sub, str) or not 8 <= len(sub) <= 64:
        return None
    return sub


async def member_role(org_id: uuid.UUID, principal: Principal | None) -> tuple[str | None, bool]:
    """(role in ``org_id``, is_superadmin) for a signed-in principal; API keys of the org act as builders."""
    if principal is None:
        return None, False
    if principal.api_key_id is not None:
        return ("builder" if principal.org_id == org_id else None), False
    if principal.user_id is None:
        return None, False
    async with system_session() as s:
        role = (
            await s.execute(
                select(Membership.role).where(Membership.org_id == org_id, Membership.user_id == principal.user_id)
            )
        ).scalar_one_or_none()
    if role is None and principal.is_superadmin:
        return "owner", True
    return role, principal.is_superadmin


def check_access(spec: InterfaceSpec, role: str | None, *, signed_in: bool, is_superadmin: bool = False) -> None:
    if not spec.requires_login:
        return
    if role is None and not is_superadmin:
        if not signed_in:
            raise Unauthorized("Inicia sesión para usar esta interfaz", code="login_required")
        raise Forbidden("Tu cuenta no tiene acceso a esta organización", code="no_access")
    if spec.auth.roles and not is_superadmin and role not in spec.auth.roles:
        raise Forbidden(
            "Tu rol no tiene acceso a esta interfaz",
            code="insufficient_role",
            details={"allowed": list(spec.auth.roles), "current": role},
        )


# ================================================================================================ public lookup


@dataclass(slots=True)
class PublicTarget:
    org: Org
    project: Project
    row: Interface
    spec: InterfaceSpec


async def _public_project(session: AsyncSession, org_slug: str, project_slug: str) -> tuple[Org, Project]:
    org = (await session.execute(select(Org).where(Org.slug == org_slug))).scalar_one_or_none()
    if org is None or org.status == "deleted":
        raise NotFound("Esta página no existe", code="not_found")
    project = (
        await session.execute(select(Project).where(Project.org_id == org.id, Project.slug == project_slug))
    ).scalar_one_or_none()
    if project is None or project.archived_at is not None:
        raise NotFound("Esta página no existe", code="not_found")
    return org, project


async def _ensure_deployed(session: AsyncSession, project: Project) -> None:
    try:
        await resolve_target(session, project.id, "production")
    except NotDeployed as exc:
        raise ApiError(
            "Este proyecto todavía no está publicado",
            code="not_deployed",
            status_code=409,
            details={"hint": "Publica el proyecto en producción desde el Studio"},
        ) from exc


def _published_spec(row: Interface) -> InterfaceSpec:
    try:
        return validate_interface(row.published_definition or {})
    except InterfaceValidationError as exc:
        log.error("interface.published_invalid", interface_id=str(row.id), issues=exc.to_list()[:5])
        raise NotFound("Esta interfaz no está disponible", code="interface_unavailable") from exc


async def published_app(org_slug: str, project_slug: str, slug: str) -> PublicTarget:
    async with system_session() as s:
        org, project = await _public_project(s, org_slug, project_slug)
        await _ensure_deployed(s, project)
        row = (
            await s.execute(select(Interface).where(Interface.project_id == project.id, Interface.slug == slug))
        ).scalar_one_or_none()
        if row is None or row.published_definition is None:
            raise NotFound("Esta interfaz no está publicada", code="interface_not_published")
    spec = _published_spec(row)
    if spec.kind != "app":
        raise NotFound("Esta interfaz no está publicada", code="interface_not_published")
    return PublicTarget(org, project, row, spec)


async def published_chat(org_slug: str, project_slug: str, agent: str) -> PublicTarget:
    async with system_session() as s:
        org, project = await _public_project(s, org_slug, project_slug)
        await _ensure_deployed(s, project)
        rows = (
            (
                await s.execute(
                    select(Interface)
                    .where(Interface.project_id == project.id, Interface.published_definition.is_not(None))
                    .order_by(Interface.published_at.desc().nulls_last())
                )
            )
            .scalars()
            .all()
        )
    for row in rows:
        definition = row.published_definition or {}
        if definition.get("kind") != "chat":
            continue
        spec, _ = check_interface(definition)
        if spec is not None and spec.chat_agent == agent:
            return PublicTarget(org, project, row, spec)
    raise NotFound("Este chat no está publicado", code="chat_not_published")


async def ensure_org_available(org_id: uuid.UUID, *, running: bool) -> None:
    """Blocked organizations serve nothing; read-only ones (billing) still serve data but run nothing."""
    state = await org_billing_state(org_id)
    if state["blocked"]:
        raise Forbidden("Este servicio no está disponible en este momento", code="org_unavailable")
    if running and state["read_only"]:
        raise PaymentRequired("Este servicio no está disponible en este momento", code="org_unavailable")


# ================================================================================================ data


@dataclass(slots=True)
class DataResult:
    source: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool = False
    elapsed_ms: float = 0.0
    column_types: list[str] = field(default_factory=list)
    policy: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "columns": self.columns,
            "column_types": self.column_types,
            "rows": self.rows,
            "row_count": self.row_count,
            "truncated": self.truncated,
            "elapsed_ms": self.elapsed_ms,
            "policy": self.policy,
        }


def _unique_columns(columns: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out: list[str] = []
    for col in columns:
        if col in seen:
            seen[col] += 1
            out.append(f"{col}_{seen[col]}")
        else:
            seen[col] = 1
            out.append(col)
    return out


async def _kb_for(project: Project, kb_id: uuid.UUID) -> KnowledgeBase:
    async with system_session() as s:
        kb = await s.get(KnowledgeBase, kb_id)
    if kb is None or kb.org_id != project.org_id or (kb.project_id is not None and kb.project_id != project.id):
        raise NotFound(
            "La base de conocimiento de este componente no existe o no pertenece al proyecto", code="kb_not_found"
        )
    return kb


def parse_component(draft: dict[str, Any]) -> AnyComponent:
    """Validate a single (unsaved) component for the editor preview."""
    try:
        comp: AnyComponent = _component_adapter.validate_python(draft)
    except ValidationError as exc:
        raise InterfaceInvalid(issues_from_pydantic(exc)) from exc
    probe = InterfaceSpec.model_validate(
        {"name": "preview", "slug": "preview", "screens": [{"id": "s", "title": "s", "components": [draft]}]}
    )
    issues = [
        ValidationIssue(i.path.replace("screens[0].components[0]", "component", 1), i.code, i.message)
        for i in semantic_issues(probe)
    ]
    if issues:
        raise InterfaceInvalid(issues)
    return comp


async def component_data(
    project: Project, component: AnyComponent, actor: Actor, inputs: dict[str, Any] | None
) -> DataResult:
    """Data of a data component (table, chart, KPI, list, calendar, approvals inbox)."""
    try:
        ctx = actor.context(inputs=clean_values(inputs))
    except BindingInputError as exc:
        raise _input_error(exc) from exc
    binding = component.binding
    if isinstance(binding, KnowledgeSqlBinding):
        await _kb_for(project, binding.kb_id)
        try:
            params = sql_params(binding, ctx)
            result = await run_readonly(
                kb_id=binding.kb_id, sql=binding.sql, params=params, limit=binding.limit, role=actor.policy_role
            )
        except BindingInputError as exc:
            raise _input_error(exc) from exc
        except KnowledgeError as exc:
            raise knowledge_api_error(exc) from exc
        columns = _unique_columns(result.columns)
        return DataResult(
            source="knowledge_sql",
            columns=columns,
            column_types=result.column_types,
            rows=[dict(zip(columns, r, strict=True)) for r in result.rows],
            row_count=result.row_count,
            truncated=result.truncated,
            elapsed_ms=result.elapsed_ms,
            policy=result.policy,
        )
    if isinstance(binding, KnowledgeSearchBinding):
        query = binding.query
        if binding.query_input and str(ctx.inputs.get(binding.query_input) or "").strip():
            query = str(ctx.inputs[binding.query_input])
        started = datetime.now(UTC)
        hits: list[dict[str, Any]] = []
        for kb_id in binding.kb_ids:
            kb = await _kb_for(project, kb_id)
            if not query.strip():
                continue
            try:
                async with system_session() as s:
                    found = await kb_search(
                        s, kb_id=kb_id, query=query, mode=binding.mode, k=binding.k, role=actor.policy_role
                    )
            except KnowledgeError as exc:
                raise knowledge_api_error(exc) from exc
            hits.extend({**h.to_dict(), "knowledge_base": kb.name} for h in found)
        hits.sort(key=lambda h: float(h.get("score") or 0), reverse=True)
        hits = hits[: binding.k]
        columns = ["filename", "heading", "content", "score", "page_from", "page_to", "knowledge_base", "file_id"]
        return DataResult(
            source="knowledge_search",
            columns=columns,
            rows=[{c: h.get(c) for c in columns} for h in hits],
            row_count=len(hits),
            elapsed_ms=round((datetime.now(UTC) - started).total_seconds() * 1000, 1),
        )
    if isinstance(binding, StaticBinding):
        rows = binding.data if isinstance(binding.data, list) else [binding.data]
        columns: list[str] = []
        for r in rows:
            for key in r:
                if key not in columns:
                    columns.append(str(key))
        return DataResult(source="static", columns=columns, rows=[dict(r) for r in rows], row_count=len(rows))
    if isinstance(binding, ApprovalsBinding) and isinstance(component, ApprovalsInboxComponent):
        return await approvals_data(project, binding, actor)
    raise ApiError("Este componente no tiene datos que consultar", code="no_data_binding")


async def approvals_data(project: Project, binding: ApprovalsBinding, actor: Actor) -> DataResult:
    if not actor.is_member:
        raise Unauthorized("Inicia sesión para ver las aprobaciones", code="login_required")
    async with system_session() as s:
        q = select(Approval).where(Approval.org_id == project.org_id, Approval.project_id == project.id)
        if binding.status == "pending":
            q = q.where(Approval.status == "pending")
        rows = (await s.execute(q.order_by(Approval.created_at.desc()).limit(200))).scalars().all()
    columns = [
        "id",
        "title",
        "workforce_name",
        "tool_name",
        "payload",
        "assigned_role",
        "status",
        "comment",
        "created_at",
        "expires_at",
        "decided_at",
        "can_decide",
    ]
    out = [
        {
            "id": str(a.id),
            "title": a.title,
            "workforce_name": a.workforce_name,
            "tool_name": a.tool_name,
            "payload": a.payload or {},
            "assigned_role": a.assigned_role,
            "status": a.status,
            "comment": a.comment,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "expires_at": a.expires_at.isoformat() if a.expires_at else None,
            "decided_at": a.decided_at.isoformat() if a.decided_at else None,
            "can_decide": a.status == "pending" and (actor.is_superadmin or at_least(actor.role, a.assigned_role)),
        }
        for a in rows
    ]
    return DataResult(source="approvals", columns=columns, rows=out, row_count=len(out))


async def decide_approval(
    project: Project,
    component: AnyComponent,
    actor: Actor,
    approval_id: uuid.UUID,
    *,
    decision: str,
    comment: str | None,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Decide an approval from an approvals inbox component (same rules and side effects as the inbox)."""
    from ..routers.approvals import ApprovalOut, DecisionIn
    from ..routers.approvals import decide_approval as decide_in_inbox

    if not isinstance(component, ApprovalsInboxComponent):
        raise ApiError("Este componente no es una bandeja de aprobaciones", code="not_approvals_inbox")
    if not actor.is_member or actor.user_id is None:
        raise Unauthorized("Inicia sesión para decidir aprobaciones", code="login_required")
    async with system_session() as s:
        approval = await s.get(Approval, approval_id)
    if approval is None or approval.project_id != project.id or approval.org_id != project.org_id:
        raise NotFound("Aprobación no encontrada")
    body = DecisionIn.model_validate({"decision": decision, "comment": comment, "payload": payload})
    out = await decide_in_inbox(approval_id, body, principal=actor.principal(), stream=False)
    if isinstance(out, ApprovalOut):
        return out.model_dump(mode="json")
    return {"id": str(approval_id)}


# ================================================================================================ runs


async def run_target(project: Project, environment: Environment_) -> dict[str, Any]:
    async with system_session() as s:
        try:
            target = await resolve_target(s, project.id, environment)
        except NotDeployed as exc:
            raise ApiError(
                "El proyecto todavía no está publicado en producción", code="not_deployed", status_code=409
            ) from exc
    return {
        "ref": target.ref,
        "environment": target.environment,
        "environment_id": str(target.environment_id) if target.environment_id else None,
        "version_id": str(target.version_id) if target.version_id else None,
    }


async def _member_exists(project: Project, name: str) -> None:
    async with system_session() as s:
        found = (
            await s.execute(select(Workforce.id).where(Workforce.project_id == project.id, Workforce.name == name))
        ).first()
    if found is None:
        raise NotFound(f"«{name}» no existe en este proyecto", code="workforce_not_found")


def _run_input(
    binding: AgentBinding | WorkflowBinding,
    ctx: RequestContext,
    *,
    title: str | None,
    labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    if isinstance(binding, WorkflowBinding):
        return workflow_input(binding, ctx)
    if binding.prompt:
        prompt = render_prompt(binding.prompt, ctx)
    else:
        values = ctx.form or ctx.row or ctx.file or ctx.inputs
        prompt = default_prompt(title=title, values=values, labels=labels) if values else (title or "")
    if not prompt.strip():
        raise ApiError("El mensaje para el agente está vacío", code="empty_prompt", status_code=422)
    return {"prompt": prompt}


def _text_of(output: Any) -> str:
    if isinstance(output, dict):
        content = output.get("content")
        if isinstance(content, list):
            return "".join(str(b.get("text", "")) for b in content if isinstance(b, dict) and b.get("type") == "text")
        if isinstance(output.get("text"), str):
            return str(output["text"])
    return output if isinstance(output, str) else ""


async def _run(
    project: Project,
    actor: Actor,
    binding: AgentBinding | WorkflowBinding,
    run_input: dict[str, Any],
    *,
    environment: Environment_,
    channel: str,
) -> dict[str, Any]:
    await ensure_org_available(project.org_id, running=True)
    await _member_exists(project, binding.workforce)
    target = await run_target(project, environment)
    body = {
        "org_id": str(project.org_id),
        "project_id": str(project.id),
        "workforce": binding.workforce,
        "input": run_input,
        "channel": channel,
        "user_id": str(actor.user_id) if actor.user_id else None,
        "external_user_id": actor.end_user,
        **target,
    }
    try:
        result = await runtime_client.run(body, timeout_s=get_settings().runtime_run_timeout_s + 30)
    except RuntimeUnavailable as exc:
        raise ApiError(
            "El entorno de ejecución no está disponible. Inténtalo de nuevo en unos segundos.",
            code="runtime_unavailable",
            status_code=503,
        ) from exc
    status = str(result.get("status") or "error")
    error = result.get("error") or (result.get("errors") or [None])[0]
    message: str | None = None
    if status not in ("success", "paused"):
        raw = error.get("message") if isinstance(error, dict) else (str(error) if error else None)
        message = raw if actor.is_member and raw else "No se pudo completar la acción"
    output = result.get("output")
    return {
        "run_id": str(result.get("run_id") or ""),
        "status": status,
        "output": output if actor.is_member or isinstance(binding, WorkflowBinding) else None,
        "text": _text_of(output),
        "error": message,
        "approvals_pending": len(result.get("approvals") or []),
        "demo": bool(result.get("demo")),
    }


async def run_component(
    project: Project,
    component: AnyComponent,
    actor: Actor,
    *,
    environment: Environment_,
    values: dict[str, Any] | None = None,
    row: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
    row_action: bool = False,
) -> dict[str, Any]:
    """Submit a form, press an action button or run a row action."""
    try:
        ctx = actor.context(inputs=clean_values(inputs), row=clean_values(row, what="columnas"))
        labels: dict[str, str] | None = None
        if row_action:
            if (
                not isinstance(component, DataTableComponent | RecordListComponent)
                or component.props.row_action is None
            ):
                raise ApiError("Este componente no tiene acción por fila", code="no_row_action")
            binding: AgentBinding | WorkflowBinding = component.props.row_action.binding
            title = component.props.row_action.label
        elif isinstance(component, FormComponent):
            ctx.form = form_values(component, values)
            labels = {f.name: f.label for f in component.props.fields}
            binding, title = component.binding, component.title
        elif isinstance(component, ActionButtonComponent):
            binding, title = component.binding, component.title or component.props.label
        else:
            raise ApiError("Este componente no ejecuta acciones", code="no_action_binding")
        run_input = _run_input(binding, ctx, title=title, labels=labels)
    except BindingInputError as exc:
        raise _input_error(exc) from exc
    return await _run(project, actor, binding, run_input, environment=environment, channel=INTERFACE_CHANNEL)


async def upload_file(
    project: Project,
    component: AnyComponent,
    actor: Actor,
    *,
    filename: str,
    data: bytes,
    mime: str | None,
    environment: Environment_,
) -> dict[str, Any]:
    """Ingest a file into the component's knowledge base, then run its workflow (if any)."""
    from .knowledge import ingest_bytes

    if not isinstance(component, FileUploadComponent):
        raise ApiError("Este componente no admite archivos", code="no_upload")
    if not actor.is_member:
        raise Unauthorized("Inicia sesión para subir archivos", code="login_required")
    await ensure_org_available(project.org_id, running=True)
    props = component.props
    name = project_svc.safe_filename(filename or "archivo")
    if props.accept and not any(name.lower().endswith(ext) for ext in props.accept):
        raise ApiError(f"Formato no admitido; usa {', '.join(props.accept)}", code="unsupported_file", status_code=415)
    if len(data) > props.max_mb * 1024 * 1024:
        raise ApiError(f"El archivo supera {props.max_mb} MB", code="file_too_large", status_code=413)
    if not data:
        raise ApiError("El archivo está vacío", code="empty_file")
    kb = await _kb_for(project, props.kb_id)
    async with system_session() as s:
        try:
            kb_file = await ingest_bytes(
                s,
                org_id=project.org_id,
                kb_id=kb.id,
                filename=name,
                data=data,
                mime=mime,
                source="upload",
                uploaded_by=actor.user_id,
            )
        except KnowledgeError as exc:
            raise knowledge_api_error(exc) from exc
        await audit.record(
            s,
            action="interface.file_uploaded",
            principal=actor.principal(),
            org_id=project.org_id,
            entity_type="kb_file",
            entity_id=kb_file.id,
            diff={"kb_id": str(kb.id), "filename": kb_file.filename, "size": kb_file.size, "component": component.id},
        )
        info = {
            "id": str(kb_file.id),
            "filename": kb_file.filename,
            "kb_id": str(kb.id),
            "mime": kb_file.mime,
            "size": kb_file.size,
            "status": kb_file.status,
        }
    run: dict[str, Any] | None = None
    if component.binding is not None:
        ctx = actor.context(file=info)
        run = await _run(
            project,
            actor,
            component.binding,
            workflow_input(component.binding, ctx),
            environment=environment,
            channel=INTERFACE_CHANNEL,
        )
    return {"file": info, "run": run}


# ================================================================================================ chat


async def conversation_for(
    project: Project, *, channel_key: str, external_user_id: str, workforce: str, provider: str = "web"
) -> Conversation:
    """The end user's thread for a chat (one per channel key and end user; created on first use)."""
    async with system_session() as s:
        await s.execute(
            pg_insert(Conversation)
            .values(
                id=uuid.uuid4(),
                org_id=project.org_id,
                project_id=project.id,
                channel_key=channel_key,
                provider=provider,
                workforce_name=workforce,
                external_user_id=external_user_id,
            )
            .on_conflict_do_nothing(constraint="uq_conversations_thread")
        )
        conv = (
            await s.execute(
                select(Conversation).where(
                    Conversation.project_id == project.id,
                    Conversation.channel_key == channel_key,
                    Conversation.external_user_id == external_user_id,
                )
            )
        ).scalar_one()
        return conv


async def find_conversation(project: Project, *, channel_key: str, external_user_id: str) -> Conversation | None:
    async with system_session() as s:
        return (
            await s.execute(
                select(Conversation).where(
                    Conversation.project_id == project.id,
                    Conversation.channel_key == channel_key,
                    Conversation.external_user_id == external_user_id,
                )
            )
        ).scalar_one_or_none()


async def pending_approvals(conversation_id: uuid.UUID) -> int:
    async with system_session() as s:
        count = (
            await s.execute(
                select(func.count())
                .select_from(Approval)
                .join(Run, Run.id == Approval.run_id)
                .where(Run.conversation_id == conversation_id, Approval.status == "pending")
            )
        ).scalar_one()
    return int(count)


async def conversation_view(conv: Conversation | None) -> dict[str, Any]:
    if conv is None:
        return {"messages": [], "pending_approvals": 0}
    messages = [
        {"role": m.get("role"), "text": m.get("text") or "", "at": m.get("at")}
        for m in (conv.messages or [])
        if isinstance(m, dict) and m.get("role") in ("user", "assistant")
    ]
    return {"messages": messages[-200:], "pending_approvals": await pending_approvals(conv.id)}


async def reset_conversation(project: Project, *, channel_key: str, external_user_id: str) -> None:
    """Start over: close the current thread (it stays in the conversations inbox) so the next message opens a
    new one without memory."""
    async with system_session() as s:
        conv = (
            await s.execute(
                select(Conversation)
                .where(
                    Conversation.project_id == project.id,
                    Conversation.channel_key == channel_key,
                    Conversation.external_user_id == external_user_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if conv is not None:
            conv.external_user_id = f"{external_user_id}#{int(datetime.now(UTC).timestamp() * 1000)}"[:255]
            conv.status = "closed"


def chat_channel_key(row: Interface, component: AnyComponent, environment: Environment_) -> str:
    suffix = ":dev" if environment == "development" else ""
    if row.kind == "chat":
        return f"public-chat:{row.id}{suffix}"
    return f"interface:{row.id}:{component.id}{suffix}"


async def chat_run_body(
    project: Project,
    row: Interface,
    component: AnyComponent,
    actor: Actor,
    *,
    message: str,
    environment: Environment_,
) -> dict[str, Any]:
    if not isinstance(component, ChatComponent):
        raise ApiError("Este componente no es un chat", code="not_chat")
    if actor.end_user is None:
        raise Unauthorized("No se pudo identificar la conversación", code="no_end_user")
    await ensure_org_available(project.org_id, running=True)
    agent = component.binding.workforce
    await _member_exists(project, agent)
    target = await run_target(project, environment)
    conv = await conversation_for(
        project,
        channel_key=chat_channel_key(row, component, environment),
        external_user_id=actor.end_user,
        workforce=agent,
    )
    if not conv.title:
        async with system_session() as s:
            stored = await s.get(Conversation, conv.id)
            if stored is not None and not stored.title:
                stored.title = message.strip()[:80]
    return {
        "org_id": str(project.org_id),
        "project_id": str(project.id),
        "workforce": agent,
        "input": {"prompt": message},
        "parent_run_id": conv.last_run_id.hex if conv.last_run_id else None,
        "channel": PUBLIC_CHAT_CHANNEL if row.kind == "chat" else INTERFACE_CHANNEL,
        "user_id": str(actor.user_id) if actor.user_id else None,
        "external_user_id": actor.end_user,
        "conversation_id": str(conv.id),
        **target,
    }


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, default=str, ensure_ascii=False)}\n\n"


async def end_user_stream(body: dict[str, Any], *, show_errors: bool) -> AsyncIterator[str]:
    """Relay a run to an end user with only what they may see.

    Engine events carry tool inputs and outputs, internal paths and costs. End users get: text deltas of the
    root agent (``TEXT``), a neutral ``ACTIVITY`` while tools run, ``APPROVAL_PENDING`` (end users never
    approve), ``DONE`` and ``ERROR``.
    """
    root: str | None = None
    segment = 0
    activity = False
    sent_text = False
    final_text = ""
    try:
        yield _sse({"type": "RUN_STARTED"})
        async for event in runtime_client.stream_run(body):
            kind = event.get("type")
            parent = event.get("parent_call_id")
            path = str(event.get("path") or "")
            if kind == "START" and parent is None and root is None:
                root = path
            elif kind == "DELTA":
                from_root = (path == root or path == f"{root}.llm") if root else len(path.split(".")) <= 2
                item = event.get("item") if isinstance(event.get("item"), dict) else {}
                assert isinstance(item, dict)
                item_type = item.get("type")
                if from_root and item_type in ("text_delta", "text"):
                    text = str(item.get("text_delta") if item_type == "text_delta" else item.get("text") or "")
                    if text:
                        if activity:
                            segment += 1
                            activity = False
                        sent_text = True
                        yield _sse({"type": "TEXT", "text": text, "segment": segment})
                elif item_type == "tool_use" and not activity:
                    activity = True
                    yield _sse({"type": "ACTIVITY"})
            elif kind == "OUTPUT" and parent is None:
                final_text = _text_of(event.get("output"))
            elif kind == "APPROVAL":
                yield _sse({"type": "APPROVAL_PENDING"})
            elif kind == "RUN_ERROR":
                err = event.get("error") if isinstance(event.get("error"), dict) else {}
                assert isinstance(err, dict)
                message = str(err.get("message") or "") if show_errors else ""
                yield _sse({"type": "ERROR", "code": str(err.get("type") or "run_error"), "message": message})
            elif kind == "RUN_FINISHED":
                status = str(event.get("status") or "error")
                if final_text and not sent_text:
                    yield _sse({"type": "TEXT", "text": final_text, "segment": segment})
                done: dict[str, Any] = {
                    "type": "DONE",
                    "status": status,
                    "run_id": str(event.get("run_id") or ""),
                    "demo": bool(event.get("demo")),
                    "approvals_pending": len(event.get("approvals") or []),
                }
                if status not in ("success", "paused"):
                    err = event.get("error") if isinstance(event.get("error"), dict) else {}
                    assert isinstance(err, dict)
                    done["message"] = str(err.get("message") or "") if show_errors else ""
                yield _sse(done)
    except RuntimeUnavailable:
        yield _sse({"type": "ERROR", "code": "runtime_unavailable", "message": ""})


# ================================================================================================ publication


async def publish_for_deployment(session: AsyncSession, project: Project, commit: str, environment: str) -> None:
    """Snapshot every ``interfaces/<slug>/interface.json`` at ``commit`` as the published definitions.

    Called by the deployment pipeline (owner session) when a version goes live. Public pages serve production
    only; the development environment always previews HEAD, so other environments change nothing. Invalid
    files are not published (and stop being served); missing ones are unpublished. Never raises for content
    problems: a broken interface must not break a deployment.
    """
    if environment != "production":
        return
    repo = repo_for(project)
    files = await interface_files(repo, commit)
    now = datetime.now(UTC)
    rows = {
        r.slug: r
        for r in (await session.execute(select(Interface).where(Interface.project_id == project.id))).scalars().all()
    }
    published: set[str] = set()
    for slug, path in files.items():
        raw = _parse_raw(await repo.read(path, commit))
        if raw is not None:
            raw = {**raw, "slug": slug}
        spec, issues = check_interface(raw) if raw is not None else (None, [])
        if spec is None:
            log.warning(
                "interface.publish_skipped_invalid",
                project_id=str(project.id),
                slug=slug,
                commit=commit[:12],
                issues=[i.to_dict() for i in issues[:5]],
            )
            continue
        snapshot = spec.to_json()
        row = rows.get(slug)
        if row is None:
            row = Interface(
                org_id=project.org_id,
                project_id=project.id,
                slug=slug,
                definition=snapshot,
                **_columns_from_spec(spec),
            )
            session.add(row)
            rows[slug] = row
        row.published_definition = snapshot
        row.published_at = now
        published.add(slug)
    for slug, row in rows.items():
        if slug not in published and row.published_definition is not None:
            row.published_definition = None
            row.published_at = None
    await session.flush()
    log.info("interfaces.published", project_id=str(project.id), commit=commit[:12], count=len(published))


async def production_status(project: Project) -> dict[str, Any]:
    async with system_session() as s:
        env = (
            await s.execute(
                select(Environment).where(Environment.project_id == project.id, Environment.name == "production")
            )
        ).scalar_one_or_none()
    return {
        "deployed": bool(env and env.deployed_version_id),
        "status": env.status if env else None,
        "url": env.url if env else None,
    }


# ================================================================================================ client view


def _client_binding(binding: Any) -> dict[str, Any] | None:
    if binding is None:
        return None
    out: dict[str, Any] = {"kind": binding.kind}
    if isinstance(binding, KnowledgeSearchBinding):
        out["query_input"] = binding.query_input
    if isinstance(binding, KnowledgeSqlBinding):
        out["inputs"] = sorted({p["input"] for p in binding.params if isinstance(p, dict) and "input" in p})
    return out


def client_definition(spec: InterfaceSpec) -> dict[str, Any]:
    """What the browser of a public page receives: layout and props, never queries, ids or mappings."""
    data = spec.to_json()
    by_id = {c.id: c for c in spec.components()}
    for screen in data["screens"]:
        for comp in screen["components"]:
            model = by_id[comp["id"]]
            comp["binding"] = _client_binding(model.binding)
            props = comp.get("props") or {}
            if isinstance(model, FileUploadComponent):
                props.pop("kb_id", None)
            if props.get("row_action"):
                props["row_action"]["binding"] = _client_binding(
                    model.props.row_action.binding
                    if isinstance(model, DataTableComponent | RecordListComponent) and model.props.row_action
                    else None
                )
    return data
