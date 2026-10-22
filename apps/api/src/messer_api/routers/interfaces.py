"""/api/v1 — interfaces of a project: CRUD (``interfaces/<slug>/interface.json`` + commit), versions, templates,
JSON Schema and validation for the Composer, and the Studio preview of every component with real data
(development environment = HEAD).

Roles: viewers read and *use* interfaces (data, forms, buttons, chat, uploads — spec 7.11); builders create,
edit, restore and delete them. Publication goes through deployments (``POST /projects/{id}/deployments``),
which snapshot the interfaces of the deployed commit.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db import Principal, rls_session
from messer_common.db.models import Interface, Org, Project
from messer_common.interfaces import TEMPLATES, InterfaceSpec, check_interface, json_schema
from messer_common.roles import at_least

from ..deps import ensure_project_access, get_db, require_role
from ..errors import ApiError, Forbidden, NotFound
from ..services import interfaces as svc
from ..services import projects as project_svc
from .studio import stream_response

router = APIRouter(tags=["interfaces"])

UPLOAD_LIMIT = 100 * 1024 * 1024


# ------------------------------------------------------------------------------------------------ schemas


class Issue(BaseModel):
    path: str
    code: str
    message: str


class InterfaceUrls(BaseModel):
    public: str | None
    embed: str | None
    widget: str | None


class InterfaceSummary(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    slug: str
    kind: str
    public: bool
    auth_required: bool
    workforce_name: str | None
    screens: int
    components: int
    valid: bool
    published: bool
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
    urls: InterfaceUrls


class InterfaceDetail(InterfaceSummary):
    definition: dict[str, Any]
    issues: list[Issue]
    warnings: list[Issue]
    commit: str | None
    published_definition: dict[str, Any] | None
    production: dict[str, Any]


class TemplateOut(BaseModel):
    key: str
    kind: str
    name: str
    name_en: str
    description: str
    description_en: str
    requires: list[str]


class CreateIn(BaseModel):
    template: str | None = Field(default=None, description="Clave de plantilla (GET /interfaces/templates)")
    definition: dict[str, Any] | None = Field(default=None, description="interface.json completo")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    slug: str | None = Field(default=None, max_length=64)
    kb_id: uuid.UUID | None = None
    table: str | None = Field(default=None, max_length=120)
    agent: str | None = Field(default=None, max_length=80)
    message: str | None = Field(default=None, max_length=500)


class UpdateIn(BaseModel):
    definition: dict[str, Any]
    message: str | None = Field(default=None, max_length=500)


class ValidateIn(BaseModel):
    definition: dict[str, Any] | str


class ValidateOut(BaseModel):
    valid: bool
    issues: list[Issue]
    warnings: list[Issue] = Field(default_factory=list)
    definition: dict[str, Any] | None = Field(default=None, description="Definición normalizada si es válida")


class VersionOut(BaseModel):
    sha: str
    message: str
    author: str
    date: datetime


class DataIn(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    draft: dict[str, Any] | None = Field(default=None, description="Componente sin guardar (vista previa del editor)")


class ActionIn(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict, description="Valores del formulario")
    row: dict[str, Any] = Field(default_factory=dict, description="Fila (acción por fila)")
    inputs: dict[str, Any] = Field(default_factory=dict)
    row_action: bool = False
    draft: dict[str, Any] | None = None


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)


class DecisionIn(BaseModel):
    decision: Literal["approve", "deny", "approve_with_changes"]
    comment: str | None = Field(default=None, max_length=4000)
    payload: dict[str, Any] | None = None


# ------------------------------------------------------------------------------------------------ helpers


def _issues(items: list[Any]) -> list[Issue]:
    return [Issue(**i.to_dict()) for i in items]


def _summary_fields(org: Org, project: Project, row: Interface, spec: InterfaceSpec | None) -> dict[str, Any]:
    definition = row.definition or {}
    screens = definition.get("screens") if isinstance(definition.get("screens"), list) else []
    assert isinstance(screens, list)
    components = sum(len(s.get("components") or []) for s in screens if isinstance(s, dict))
    return {
        "id": row.id,
        "project_id": row.project_id,
        "name": row.name,
        "slug": row.slug,
        "kind": row.kind,
        "public": row.public,
        "auth_required": row.auth_required,
        "workforce_name": row.workforce_name,
        "screens": len(screens),
        "components": components,
        "valid": spec is not None,
        "published": row.published_definition is not None,
        "published_at": row.published_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "urls": InterfaceUrls(**svc.public_urls(org, project, row, spec)),
    }


async def _org(session: AsyncSession, org_id: uuid.UUID) -> Org:
    org = await session.get(Org, org_id)
    if org is None:
        raise NotFound("Organización no encontrada")
    return org


async def _detail(session: AsyncSession, project: Project, row: Interface) -> InterfaceDetail:
    state = await svc.load_state(project, row)
    warnings = await svc.reference_warnings(project, state.spec) if state.spec is not None else []
    org = await _org(session, project.org_id)
    return InterfaceDetail(
        **_summary_fields(org, project, row, state.spec),
        definition=state.definition,
        issues=_issues(state.issues),
        warnings=_issues(warnings),
        commit=state.commit,
        published_definition=row.published_definition,
        production=await svc.production_status(project),
    )


async def _context(
    session: AsyncSession, principal: Principal, interface_id: uuid.UUID
) -> tuple[Project, Interface, InterfaceSpec]:
    row = await svc.get_row(session, principal, interface_id)
    ensure_project_access(principal, row.project_id)
    project = await project_svc.get_project(session, row.project_id)
    spec, issues = check_interface(row.definition or {})
    if spec is None:
        raise svc.InterfaceInvalid(issues, "Corrige los errores de la interfaz antes de usarla")
    return project, row, spec


def _component(spec: InterfaceSpec, component_id: str, draft: dict[str, Any] | None, principal: Principal) -> Any:
    if draft is not None:
        if not (principal.is_superadmin or at_least(principal.role, "builder")):
            raise Forbidden("Solo los constructores pueden previsualizar cambios sin guardar", code="insufficient_role")
        comp = svc.parse_component(draft)
        if comp.id != component_id:
            raise ApiError("El id del componente no coincide", code="component_mismatch")
        return comp
    comp = spec.component(component_id)
    if comp is None:
        raise NotFound(f"El componente «{component_id}» no existe en esta interfaz", code="component_not_found")
    return comp


# ------------------------------------------------------------------------------------------------ catalog


@router.get("/interfaces/schema")
async def interface_schema(_: Principal = Depends(require_role("viewer"))) -> dict[str, Any]:
    """JSON Schema of interface.json (the Composer composes against it)."""
    return json_schema()


@router.get("/interfaces/templates", response_model=list[TemplateOut])
async def interface_templates(_: Principal = Depends(require_role("viewer"))) -> list[TemplateOut]:
    return [
        TemplateOut(
            key=t.key,
            kind=t.kind,
            name=t.name,
            name_en=t.name_en,
            description=t.description,
            description_en=t.description_en,
            requires=list(t.requires),
        )
        for t in TEMPLATES
    ]


@router.post("/interfaces/validate", response_model=ValidateOut)
async def validate_definition(body: ValidateIn, _: Principal = Depends(require_role("viewer"))) -> ValidateOut:
    spec, issues = check_interface(body.definition)
    return ValidateOut(valid=spec is not None, issues=_issues(issues), definition=spec.to_json() if spec else None)


# ------------------------------------------------------------------------------------------------ CRUD


@router.get("/projects/{project_id}/interfaces", response_model=list[InterfaceSummary])
async def list_interfaces(
    project_id: uuid.UUID,
    principal: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db),
    kind: Literal["app", "chat"] | None = None,
) -> list[InterfaceSummary]:
    ensure_project_access(principal, project_id)
    project = await project_svc.get_project(session, project_id)
    await svc.sync_index(project)
    q = select(Interface).where(Interface.project_id == project.id)
    if kind:
        q = q.where(Interface.kind == kind)
    rows = (await session.execute(q.order_by(Interface.updated_at.desc()))).scalars().all()
    org = await _org(session, project.org_id)
    out: list[InterfaceSummary] = []
    for row in rows:
        spec, _ = check_interface(row.definition or {})
        out.append(InterfaceSummary(**_summary_fields(org, project, row, spec)))
    return out


@router.post("/projects/{project_id}/interfaces", response_model=InterfaceDetail, status_code=201)
async def create_interface(
    project_id: uuid.UUID,
    body: CreateIn,
    principal: Principal = Depends(require_role("builder")),
    session: AsyncSession = Depends(get_db),
) -> InterfaceDetail:
    """Create from a template (``template`` + its parameters) or from a full definition (Composer)."""
    ensure_project_access(principal, project_id)
    project = await project_svc.get_project(session, project_id)
    if body.definition is not None:
        definition = dict(body.definition)
        if body.name:
            definition["name"] = body.name
        if body.slug:
            definition["slug"] = body.slug
        elif not definition.get("slug") and definition.get("name"):
            definition["slug"] = await svc.unique_slug(session, project, str(definition["name"]))
    else:
        template = body.template or "blank_app"
        name = (body.name or "").strip() or "Nueva interfaz"
        definition = await svc.definition_from_template(
            session,
            project,
            template=template,
            name=name,
            slug=body.slug,
            kb_id=body.kb_id,
            table=body.table,
            agent=body.agent,
        )
    row, _ = await svc.create_interface(session, principal, project, definition=definition, message=body.message)
    return await _detail(session, project, row)


@router.post("/projects/{project_id}/interfaces/validate", response_model=ValidateOut)
async def validate_for_project(
    project_id: uuid.UUID,
    body: ValidateIn,
    principal: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db),
) -> ValidateOut:
    """Validate a definition and check its references (knowledge bases, agents, workflows) in the project."""
    ensure_project_access(principal, project_id)
    project = await project_svc.get_project(session, project_id)
    spec, issues = check_interface(body.definition)
    warnings = await svc.reference_warnings(project, spec) if spec is not None else []
    return ValidateOut(
        valid=spec is not None,
        issues=_issues(issues),
        warnings=_issues(warnings),
        definition=spec.to_json() if spec else None,
    )


@router.get("/interfaces/{interface_id}", response_model=InterfaceDetail)
async def get_interface(
    interface_id: uuid.UUID,
    principal: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db),
) -> InterfaceDetail:
    row = await svc.get_row(session, principal, interface_id)
    ensure_project_access(principal, row.project_id)
    project = await project_svc.get_project(session, row.project_id)
    return await _detail(session, project, row)


@router.put("/interfaces/{interface_id}", response_model=InterfaceDetail)
async def update_interface(
    interface_id: uuid.UUID,
    body: UpdateIn,
    principal: Principal = Depends(require_role("builder")),
    session: AsyncSession = Depends(get_db),
) -> InterfaceDetail:
    """Replace the definition: validates, writes interface.json and commits (a version of the project)."""
    row = await svc.get_row(session, principal, interface_id)
    ensure_project_access(principal, row.project_id)
    project = await project_svc.get_project(session, row.project_id)
    await svc.update_interface(session, principal, project, row, definition=body.definition, message=body.message)
    return await _detail(session, project, row)


@router.delete("/interfaces/{interface_id}", status_code=204)
async def delete_interface(
    interface_id: uuid.UUID,
    principal: Principal = Depends(require_role("builder")),
    session: AsyncSession = Depends(get_db),
) -> None:
    row = await svc.get_row(session, principal, interface_id)
    ensure_project_access(principal, row.project_id)
    project = await project_svc.get_project(session, row.project_id)
    await svc.delete_interface(session, principal, project, row)


@router.get("/interfaces/{interface_id}/versions", response_model=list[VersionOut])
async def list_versions(
    interface_id: uuid.UUID,
    principal: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[VersionOut]:
    """Commits that changed this interface (versions through the project's history)."""
    row = await svc.get_row(session, principal, interface_id)
    ensure_project_access(principal, row.project_id)
    project = await project_svc.get_project(session, row.project_id)
    return [
        VersionOut(sha=c.sha, message=c.message, author=c.author, date=c.date)
        for c in await svc.versions(project, row, limit)
    ]


@router.get("/interfaces/{interface_id}/versions/{sha}")
async def get_version(
    interface_id: uuid.UUID,
    sha: str,
    principal: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await svc.get_row(session, principal, interface_id)
    ensure_project_access(principal, row.project_id)
    project = await project_svc.get_project(session, row.project_id)
    _check_sha(sha)
    return {"sha": sha, "definition": await svc.definition_at(project, row, sha)}


@router.post("/interfaces/{interface_id}/versions/{sha}/restore", response_model=InterfaceDetail)
async def restore_version(
    interface_id: uuid.UUID,
    sha: str,
    principal: Principal = Depends(require_role("builder")),
    session: AsyncSession = Depends(get_db),
) -> InterfaceDetail:
    row = await svc.get_row(session, principal, interface_id)
    ensure_project_access(principal, row.project_id)
    project = await project_svc.get_project(session, row.project_id)
    _check_sha(sha)
    await svc.restore_version(session, principal, project, row, sha)
    return await _detail(session, project, row)


def _check_sha(sha: str) -> None:
    if not (4 <= len(sha) <= 64 and all(c in "0123456789abcdef" for c in sha.lower())):
        raise NotFound("Versión no encontrada", code="version_not_found")


# ------------------------------------------------------------------------------------------------ preview / use


@router.post("/interfaces/{interface_id}/components/{component_id}/data")
async def component_data(
    interface_id: uuid.UUID,
    component_id: str,
    body: DataIn,
    principal: Principal = Depends(require_role("viewer")),
) -> dict[str, Any]:
    """Real data of a component (SQL bindings run read-only with the caller's knowledge policies)."""
    async with rls_session(principal) as session:
        project, _, spec = await _context(session, principal, interface_id)
    comp = _component(spec, component_id, body.draft, principal)
    result = await svc.component_data(project, comp, svc.actor_from_principal(principal), body.inputs)
    return result.to_dict()


@router.post("/interfaces/{interface_id}/components/{component_id}/action")
async def component_action(
    interface_id: uuid.UUID,
    component_id: str,
    body: ActionIn,
    principal: Principal = Depends(require_role("viewer")),
) -> dict[str, Any]:
    """Submit a form, press a button or run a row action (development environment)."""
    async with rls_session(principal) as session:
        project, _, spec = await _context(session, principal, interface_id)
    comp = _component(spec, component_id, body.draft, principal)
    return await svc.run_component(
        project,
        comp,
        svc.actor_from_principal(principal),
        environment="development",
        values=body.values,
        row=body.row,
        inputs=body.inputs,
        row_action=body.row_action,
    )


@router.post("/interfaces/{interface_id}/components/{component_id}/upload", status_code=201)
async def component_upload(
    interface_id: uuid.UUID,
    component_id: str,
    file: UploadFile = File(...),
    principal: Principal = Depends(require_role("viewer")),
) -> dict[str, Any]:
    async with rls_session(principal) as session:
        project, _, spec = await _context(session, principal, interface_id)
    comp = _component(spec, component_id, None, principal)
    data = await file.read(UPLOAD_LIMIT + 1)
    return await svc.upload_file(
        project,
        comp,
        svc.actor_from_principal(principal),
        filename=file.filename or "archivo",
        data=data,
        mime=file.content_type,
        environment="development",
    )


@router.post("/interfaces/{interface_id}/components/{component_id}/chat")
async def component_chat(
    interface_id: uuid.UUID,
    component_id: str,
    body: ChatIn,
    principal: Principal = Depends(require_role("viewer")),
) -> StreamingResponse:
    """Chat with the component's agent (streamed; per-user memory)."""
    async with rls_session(principal) as session:
        project, row, spec = await _context(session, principal, interface_id)
    comp = _component(spec, component_id, None, principal)
    run_body = await svc.chat_run_body(
        project, row, comp, svc.actor_from_principal(principal), message=body.message, environment="development"
    )
    return stream_response(svc.end_user_stream(run_body, show_errors=True))


@router.get("/interfaces/{interface_id}/components/{component_id}/conversation")
async def component_conversation(
    interface_id: uuid.UUID,
    component_id: str,
    principal: Principal = Depends(require_role("viewer")),
) -> dict[str, Any]:
    async with rls_session(principal) as session:
        project, row, spec = await _context(session, principal, interface_id)
    comp = _component(spec, component_id, None, principal)
    actor = svc.actor_from_principal(principal)
    conv = await svc.find_conversation(
        project, channel_key=svc.chat_channel_key(row, comp, "development"), external_user_id=actor.end_user or ""
    )
    return await svc.conversation_view(conv)


@router.delete("/interfaces/{interface_id}/components/{component_id}/conversation", status_code=204)
async def reset_component_conversation(
    interface_id: uuid.UUID,
    component_id: str,
    principal: Principal = Depends(require_role("viewer")),
) -> None:
    async with rls_session(principal) as session:
        project, row, spec = await _context(session, principal, interface_id)
    comp = _component(spec, component_id, None, principal)
    actor = svc.actor_from_principal(principal)
    await svc.reset_conversation(
        project, channel_key=svc.chat_channel_key(row, comp, "development"), external_user_id=actor.end_user or ""
    )


@router.post("/interfaces/{interface_id}/components/{component_id}/approvals/{approval_id}/decision")
async def component_decision(
    interface_id: uuid.UUID,
    component_id: str,
    approval_id: uuid.UUID,
    body: DecisionIn,
    principal: Principal = Depends(require_role("viewer")),
) -> dict[str, Any]:
    async with rls_session(principal) as session:
        project, _, spec = await _context(session, principal, interface_id)
    comp = _component(spec, component_id, None, principal)
    return await svc.decide_approval(
        project,
        comp,
        svc.actor_from_principal(principal),
        approval_id,
        decision=body.decision,
        comment=body.comment,
        payload=body.payload,
    )
