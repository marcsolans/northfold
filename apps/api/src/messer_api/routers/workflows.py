"""/api/v1/projects/{project_id}/workflows — Studio workflow builder: graph, code, layout, custom nodes, runs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import runtime_client
from messer_common.db import Principal, rls_session
from messer_common.db.models import Connection, Connector, KnowledgeBase, Project, Run, Trigger, Workforce
from messer_common.models_config import TIERS, tier_model
from messer_common.runtime_client import RuntimeUnavailable
from messer_common.studio.workflow_spec import (
    MAX_LOOP_ITEMS,
    MAX_WAIT_SECONDS,
    STARTERS,
    CustomFunction,
    Position,
    WorkflowConfig,
    palette_node_types,
    palette_tools,
    validate_workflow,
)

from ..deps import ensure_project_access, get_db, require_role
from ..errors import ApiError
from ..services import projects as projects_svc
from ..services import workflows as svc
from .studio import relay_run, stream_response

router = APIRouter(prefix="/projects/{project_id}/workflows", tags=["workflows"])

ROLES = ("viewer", "builder", "admin", "owner")


class LastRun(BaseModel):
    id: uuid.UUID
    status: str
    started_at: datetime


class WorkflowSummary(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    source_mode: str
    current_version: int
    updated_at: datetime
    nodes: int
    triggers: int
    last_run: LastRun | None


class CustomNodesOut(BaseModel):
    code: str
    functions: list[CustomFunction]
    error: dict[str, Any] | None = None


class WorkflowDetail(BaseModel):
    id: uuid.UUID
    name: str
    kind: str = "workflow"
    description: str
    path: str
    source_mode: str
    current_version: int
    updated_at: datetime
    commit: str
    code: str
    config: WorkflowConfig | None
    viewport: dict[str, float]
    positions: dict[str, Position]
    custom_nodes: CustomNodesOut
    flow: dict[str, Any] | None = None
    flow_error: str | None = None


class CreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=63, pattern=r"^[a-z][a-z0-9_]*$")
    description: str = Field(default="", max_length=2000)
    template: Literal["blank", "approval", "classify"] = "blank"
    config: WorkflowConfig | None = None


class Viewport(BaseModel):
    x: float = 0
    y: float = 0
    zoom: float = Field(default=1, gt=0, le=10)


class GraphIn(BaseModel):
    config: WorkflowConfig
    viewport: Viewport | None = None
    message: str | None = Field(default=None, max_length=300)


class ValidateIn(BaseModel):
    config: WorkflowConfig


class CodeIn(BaseModel):
    code: str = Field(max_length=500_000)


class LayoutIn(BaseModel):
    positions: dict[str, Position] = Field(default_factory=dict, max_length=500)
    viewport: Viewport | None = None


class CustomCodeIn(BaseModel):
    code: str = Field(max_length=500_000)


class CustomNodeIn(BaseModel):
    name: str = Field(min_length=1, max_length=63)
    description: str = Field(default="", max_length=300)


class RunIn(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    event: dict[str, Any] | None = None


async def _project(db: AsyncSession, principal: Principal, project_id: uuid.UUID) -> Project:
    ensure_project_access(principal, project_id)
    return await projects_svc.get_project(db, project_id)


async def _detail(db: AsyncSession, project: Project, member: Workforce, *, with_flow: bool = True) -> WorkflowDetail:
    state = await svc.load_state(db, project, member)
    flow: dict[str, Any] | None = None
    flow_error: str | None = None
    if member.source_mode == "code" and with_flow:
        try:
            flow = await runtime_client.flow(project.id, member.name)
        except RuntimeUnavailable as exc:
            flow_error = str(exc)[:500]
    return WorkflowDetail(
        id=member.id,
        name=member.name,
        description=member.description,
        path=member.path,
        source_mode=member.source_mode,
        current_version=member.current_version,
        updated_at=member.updated_at,
        commit=state.commit,
        code=state.code,
        config=state.config,
        viewport=state.viewport,
        positions=state.positions,
        custom_nodes=CustomNodesOut(code=state.custom_code, functions=state.custom_functions, error=state.custom_error),
        flow=flow,
        flow_error=flow_error,
    )


# --------------------------------------------------------------------------------------------- list/create


@router.get("", response_model=list[WorkflowSummary])
async def list_workflows(
    project_id: uuid.UUID, principal: Principal = Depends(require_role("viewer")), db: AsyncSession = Depends(get_db)
) -> list[WorkflowSummary]:
    project = await _project(db, principal, project_id)
    members = (
        (
            await db.execute(
                select(Workforce)
                .where(Workforce.project_id == project.id, Workforce.kind == "workflow")
                .order_by(Workforce.name)
            )
        )
        .scalars()
        .all()
    )
    ids = [m.id for m in members]
    trigger_counts: dict[uuid.UUID, int] = {}
    last_runs: dict[uuid.UUID, LastRun] = {}
    if ids:
        for workforce_id, n in (
            await db.execute(
                select(Trigger.workforce_id, func.count())
                .where(Trigger.workforce_id.in_(ids))
                .group_by(Trigger.workforce_id)
            )
        ).all():
            trigger_counts[workforce_id] = int(n)
        latest = (
            select(Run.workforce_id, func.max(Run.started_at).label("at"))
            .where(Run.workforce_id.in_(ids), Run.parent_run_id.is_(None))
            .group_by(Run.workforce_id)
            .subquery()
        )
        rows = (
            (
                await db.execute(
                    select(Run).join(
                        latest, (Run.workforce_id == latest.c.workforce_id) & (Run.started_at == latest.c.at)
                    )
                )
            )
            .scalars()
            .all()
        )
        for run in rows:
            if run.workforce_id is not None:
                last_runs[run.workforce_id] = LastRun(id=run.id, status=run.status, started_at=run.started_at)
    return [
        WorkflowSummary(
            id=m.id,
            name=m.name,
            description=m.description,
            source_mode=m.source_mode,
            current_version=m.current_version,
            updated_at=m.updated_at,
            nodes=len((m.config_json or {}).get("nodes") or []),
            triggers=trigger_counts.get(m.id, 0),
            last_run=last_runs.get(m.id),
        )
        for m in members
    ]


@router.post("", response_model=WorkflowDetail, status_code=201)
async def create_workflow(
    project_id: uuid.UUID,
    body: CreateIn,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> WorkflowDetail:
    project = await _project(db, principal, project_id)
    member = await svc.create_workflow(
        db, principal, project, name=body.name, description=body.description, template=body.template, config=body.config
    )
    return await _detail(db, project, member)


@router.get("/palette")
async def palette(
    project_id: uuid.UUID, principal: Principal = Depends(require_role("viewer")), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Node palette: node types (config JSON schemas), built-in tools, agents and workflows of the project, active
    connections and knowledge bases of the organization."""
    project = await _project(db, principal, project_id)
    members = (
        (await db.execute(select(Workforce).where(Workforce.project_id == project.id).order_by(Workforce.name)))
        .scalars()
        .all()
    )
    connector_names = {c.key: c.name for c in (await db.execute(select(Connector))).scalars()}
    connections = (
        (
            await db.execute(
                select(Connection)
                .where(Connection.org_id == project.org_id, Connection.status.in_(("active", "demo")))
                .order_by(Connection.name)
            )
        )
        .scalars()
        .all()
    )
    kbs = (
        (
            await db.execute(
                select(KnowledgeBase).where(KnowledgeBase.org_id == project.org_id).order_by(KnowledgeBase.name)
            )
        )
        .scalars()
        .all()
    )
    return {
        "node_types": palette_node_types(),
        "templates": list(STARTERS),
        "tools": palette_tools(),
        "agents": [{"name": m.name, "description": m.description} for m in members if m.kind == "agent"],
        "workflows": [{"name": m.name, "description": m.description} for m in members if m.kind == "workflow"],
        "connections": [
            {
                "id": str(c.id),
                "name": c.name,
                "connector_key": c.connector_key,
                "connector_name": connector_names.get(c.connector_key, c.connector_key),
                "status": c.status,
                "demo": c.demo,
            }
            for c in connections
        ],
        "knowledge_bases": [{"id": str(k.id), "name": k.name, "description": k.description} for k in kbs],
        "model_tiers": [{"tier": t, "model": tier_model(t)} for t in TIERS],
        "default_tier": project.default_model_tier,
        "roles": list(ROLES),
        "limits": {"max_wait_seconds": MAX_WAIT_SECONDS, "max_loop_items": MAX_LOOP_ITEMS},
    }


# ------------------------------------------------------------------------------------------------ detail


@router.get("/{name}", response_model=WorkflowDetail)
async def get_workflow(
    project_id: uuid.UUID,
    name: str,
    principal: Principal = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> WorkflowDetail:
    """Graph (with positions) in config mode; in code mode the graph introspected by the runtime (``flow``)."""
    project = await _project(db, principal, project_id)
    return await _detail(db, project, await svc.get_workflow(db, project, name))


@router.put("/{name}/graph", response_model=WorkflowDetail)
async def put_graph(
    project_id: uuid.UUID,
    name: str,
    body: GraphIn,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> WorkflowDetail:
    """Save the canvas: validates the graph, regenerates ``workflow.py`` and writes ``layout.json`` (one commit)."""
    project = await _project(db, principal, project_id)
    member = await svc.get_workflow(db, project, name)
    await svc.update_graph(
        db, principal, project, member, body.config, body.viewport.model_dump() if body.viewport else None, body.message
    )
    return await _detail(db, project, member, with_flow=False)


@router.post("/{name}/validate")
async def validate(
    project_id: uuid.UUID,
    name: str,
    body: ValidateIn,
    principal: Principal = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Problems of a graph without saving it (cycles, bindings, missing configuration…)."""
    project = await _project(db, principal, project_id)
    member = await svc.get_workflow(db, project, name)
    state = await svc.load_state(db, project, member)
    members = await svc.members_by_kind(db, project, exclude=member.name)
    issues = validate_workflow(body.config, members=members, custom_functions=[f.name for f in state.custom_functions])
    if body.config.name != member.name:
        issues.insert(0, {"code": "rename_unsupported", "message": "El nombre de un flujo no se puede cambiar"})
    return {"valid": not issues, "issues": issues}


@router.put("/{name}/code", response_model=WorkflowDetail)
async def put_code(
    project_id: uuid.UUID,
    name: str,
    body: CodeIn,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> WorkflowDetail:
    """Save hand-written ``workflow.py``: syntax check, then the canvas follows when the code parses back
    (otherwise the workflow switches to code mode)."""
    project = await _project(db, principal, project_id)
    member = await svc.get_workflow(db, project, name)
    await svc.update_code(db, principal, project, member, body.code)
    return await _detail(db, project, member)


@router.put("/{name}/layout")
async def put_layout(
    project_id: uuid.UUID,
    name: str,
    body: LayoutIn,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Node positions and viewport only (``layout.json``)."""
    project = await _project(db, principal, project_id)
    member = await svc.get_workflow(db, project, name)
    commit = await svc.update_layout(
        db, principal, project, member, body.positions, body.viewport.model_dump() if body.viewport else None
    )
    return {"commit": commit}


# ------------------------------------------------------------------------------------------ custom nodes


async def _custom_out(db: AsyncSession, project: Project, member: Workforce) -> CustomNodesOut:
    state = await svc.load_state(db, project, member)
    return CustomNodesOut(code=state.custom_code, functions=state.custom_functions, error=state.custom_error)


@router.get("/{name}/custom-nodes", response_model=CustomNodesOut)
async def get_custom_nodes(
    project_id: uuid.UUID,
    name: str,
    principal: Principal = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> CustomNodesOut:
    project = await _project(db, principal, project_id)
    return await _custom_out(db, project, await svc.get_workflow(db, project, name))


@router.put("/{name}/custom-nodes", response_model=CustomNodesOut)
async def put_custom_nodes(
    project_id: uuid.UUID,
    name: str,
    body: CustomCodeIn,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> CustomNodesOut:
    """Save ``nodes.py`` (syntax checked; functions used on the canvas cannot disappear)."""
    project = await _project(db, principal, project_id)
    member = await svc.get_workflow(db, project, name)
    await svc.save_custom_nodes(db, principal, project, member, body.code)
    return await _custom_out(db, project, member)


@router.post("/{name}/custom-nodes", response_model=CustomNodesOut, status_code=201)
async def add_custom_node(
    project_id: uuid.UUID,
    name: str,
    body: CustomNodeIn,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> CustomNodesOut:
    """Append a new function (a starting stub) to ``nodes.py``."""
    project = await _project(db, principal, project_id)
    member = await svc.get_workflow(db, project, name)
    await svc.add_custom_node(db, principal, project, member, body.name, body.description)
    return await _custom_out(db, project, member)


@router.delete("/{name}/custom-nodes/{function}", response_model=CustomNodesOut)
async def delete_custom_node(
    project_id: uuid.UUID,
    name: str,
    function: str,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> CustomNodesOut:
    project = await _project(db, principal, project_id)
    member = await svc.get_workflow(db, project, name)
    await svc.remove_custom_node(db, principal, project, member, function)
    return await _custom_out(db, project, member)


# -------------------------------------------------------------------------------------------------- runs


@router.post("/{name}/run")
async def run_workflow(
    project_id: uuid.UUID, name: str, body: RunIn, principal: Principal = Depends(require_role("builder"))
) -> StreamingResponse:
    """Manual run of the latest code with a JSON input; streams the engine events (SSE) like the Studio chat.

    The input follows the trigger convention: the declared inputs plus ``event`` (a sample trigger payload).
    """
    ensure_project_access(principal, project_id)
    async with rls_session(principal) as session:
        project = await projects_svc.get_project(session, project_id)
        member = await svc.get_workflow(session, project, name)
        state = await svc.load_state(session, project, member)
    if state.config is not None:
        missing = [i.name for i in state.config.inputs if i.required and body.input.get(i.name) in (None, "")]
        if missing:
            raise ApiError(
                f"Faltan entradas obligatorias: {', '.join(missing)}",
                code="missing_inputs",
                details={"missing": missing},
            )
    run_input = {**body.input, "event": body.event or {"type": "manual"}}
    run_body = {
        "org_id": str(project.org_id),
        "project_id": str(project.id),
        "workforce": member.name,
        "ref": "HEAD",
        "input": run_input,
        "environment": "development",
        "channel": "studio",
        "user_id": str(principal.user_id) if principal.user_id else None,
    }
    first = {"type": "WORKFLOW_RUN", "workflow": member.name, "commit": state.commit, "input": run_input}
    return stream_response(relay_run(run_body, first))
