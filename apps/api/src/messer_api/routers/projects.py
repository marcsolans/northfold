"""/api/v1/projects — projects, files, workforce members (agents/workflows), versions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common.db import Principal, system_session
from messer_common.db.models import Environment, Project, Run, Version, Workforce
from messer_common.projects_repo import ProjectRepo, RepoError
from messer_common.security import constant_time_equals
from messer_common.settings import get_settings
from messer_common.studio.agent_spec import BUILTIN_TOOLS, AgentConfig

from ..deps import ensure_project_access, get_db, require_role
from ..errors import ApiError, NotFound, Unauthorized
from ..services import projects as svc

router = APIRouter(prefix="/projects", tags=["projects"])
public_router = APIRouter(tags=["internal"])


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    default_model_tier: Literal["fast", "standard", "powerful"] = "standard"


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    default_model_tier: Literal["fast", "standard", "powerful"] | None = None


class ProjectOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str
    default_model_tier: str
    template_id: str | None
    github_repo: str | None
    created_at: datetime
    updated_at: datetime
    agents: int = 0
    workflows: int = 0
    runs_30d: int = 0


class MemberOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    description: str
    path: str
    source_mode: str
    current_version: int
    guard_enabled: bool
    updated_at: datetime


class MemberDetail(MemberOut):
    config: dict[str, Any]
    code: str
    commit: str


class AgentCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=63, pattern=r"^[a-z][a-z0-9_]*$")
    description: str = ""
    config: AgentConfig | None = None


class CodeIn(BaseModel):
    code: str = Field(max_length=500_000)


class VersionIn(BaseModel):
    message: str = Field(default="", max_length=500)


class VersionOut(BaseModel):
    id: uuid.UUID
    version: int
    git_commit: str
    message: str
    author_id: uuid.UUID | None
    created_at: datetime


def _project_out(p: Project, counts: dict[str, int] | None = None) -> ProjectOut:
    c = counts or {}
    return ProjectOut(
        id=p.id,
        name=p.name,
        slug=p.slug,
        description=p.description,
        default_model_tier=p.default_model_tier,
        template_id=p.template_id,
        github_repo=p.github_repo,
        created_at=p.created_at,
        updated_at=p.updated_at,
        agents=c.get("agent", 0),
        workflows=c.get("workflow", 0),
        runs_30d=c.get("runs", 0),
    )


def _member_out(m: Workforce) -> MemberOut:
    return MemberOut(
        id=m.id,
        name=m.name,
        kind=m.kind,
        description=m.description,
        path=m.path,
        source_mode=m.source_mode,
        current_version=m.current_version,
        guard_enabled=m.guard_enabled,
        updated_at=m.updated_at,
    )


async def _project(db: AsyncSession, principal: Principal, project_id: uuid.UUID) -> Project:
    ensure_project_access(principal, project_id)
    return await svc.get_project(db, project_id)


# ------------------------------------------------------------------------------------------- projects


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    principal: Principal = Depends(require_role("viewer")), db: AsyncSession = Depends(get_db)
) -> list[ProjectOut]:
    q = select(Project).where(Project.org_id == principal.org_id, Project.archived_at.is_(None))
    if principal.project_id:
        q = q.where(Project.id == principal.project_id)
    projects = (await db.execute(q.order_by(Project.updated_at.desc()))).scalars().all()
    ids = [p.id for p in projects]
    counts: dict[uuid.UUID, dict[str, int]] = {pid: {} for pid in ids}
    if ids:
        for pid, kind, n in (
            await db.execute(
                select(Workforce.project_id, Workforce.kind, func.count())
                .where(Workforce.project_id.in_(ids))
                .group_by(Workforce.project_id, Workforce.kind)
            )
        ).all():
            counts[pid][kind] = int(n)
        since = datetime.now(UTC) - timedelta(days=30)
        for pid, n in (
            await db.execute(
                select(Run.project_id, func.count())
                .where(Run.project_id.in_(ids), Run.started_at >= since)
                .group_by(Run.project_id)
            )
        ).all():
            counts[pid]["runs"] = int(n)
    return [_project_out(p, counts.get(p.id)) for p in projects]


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(
    body: ProjectIn, principal: Principal = Depends(require_role("builder")), db: AsyncSession = Depends(get_db)
) -> ProjectOut:
    project = await svc.create_project(
        db, principal, name=body.name, description=body.description, default_model_tier=body.default_model_tier
    )
    return _project_out(project)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: uuid.UUID, principal: Principal = Depends(require_role("viewer")), db: AsyncSession = Depends(get_db)
) -> ProjectOut:
    project = await _project(db, principal, project_id)
    counts: dict[str, int] = {}
    for kind, n in (
        await db.execute(
            select(Workforce.kind, func.count()).where(Workforce.project_id == project.id).group_by(Workforce.kind)
        )
    ).all():
        counts[kind] = int(n)
    return _project_out(project, counts)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: uuid.UUID,
    body: ProjectPatch,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    project = await _project(db, principal, project_id)
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(project, key, value)
    if changes:
        await svc.update_manifest(db, principal, project, changes)
        await audit.record(
            db, action="project.updated", principal=principal, entity_type="project", entity_id=project.id, diff=changes
        )
    return _project_out(project)


@router.delete("/{project_id}", status_code=204)
async def archive_project(
    project_id: uuid.UUID, principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> Response:
    project = await _project(db, principal, project_id)
    project.archived_at = datetime.now(UTC)
    await audit.record(db, action="project.archived", principal=principal, entity_type="project", entity_id=project.id)
    return Response(status_code=204)


@router.get("/{project_id}/environments")
async def list_environments(
    project_id: uuid.UUID, principal: Principal = Depends(require_role("viewer")), db: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
    await _project(db, principal, project_id)
    envs = (await db.execute(select(Environment).where(Environment.project_id == project_id))).scalars()
    return [
        {
            "id": str(e.id),
            "name": e.name,
            "status": e.status,
            "url": e.url,
            "custom_domain": e.custom_domain,
            "deployed_version_id": str(e.deployed_version_id) if e.deployed_version_id else None,
        }
        for e in envs
    ]


# ------------------------------------------------------------------------------------------- files


@router.get("/{project_id}/files")
async def list_files(
    project_id: uuid.UUID,
    ref: str = "HEAD",
    principal: Principal = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    project = await _project(db, principal, project_id)
    repo = svc.repo_for(project)
    try:
        return {"ref": await repo.resolve(ref), "files": await repo.list_files(ref)}
    except RepoError as exc:
        raise NotFound("Referencia no encontrada") from exc


@router.get("/{project_id}/files/content")
async def file_content(
    project_id: uuid.UUID,
    path: str,
    ref: str = "HEAD",
    principal: Principal = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    project = await _project(db, principal, project_id)
    try:
        content = await svc.repo_for(project).read(path, ref)
    except RepoError as exc:
        raise ApiError(str(exc), code="invalid_path") from exc
    if content is None:
        raise NotFound("Archivo no encontrado")
    return {"path": path, "ref": ref, "content": content}


@router.get("/{project_id}/commits")
async def commits(
    project_id: uuid.UUID,
    path: str | None = None,
    limit: int = Query(default=50, le=200),
    principal: Principal = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    project = await _project(db, principal, project_id)
    log = await svc.repo_for(project).log(path, limit)
    return [{"sha": c.sha, "message": c.message, "author": c.author, "date": c.date.isoformat()} for c in log]


# ------------------------------------------------------------------------------------------- workforce


@router.get("/{project_id}/workforce", response_model=list[MemberOut])
async def list_members(
    project_id: uuid.UUID,
    kind: Literal["agent", "workflow"] | None = None,
    principal: Principal = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> list[MemberOut]:
    await _project(db, principal, project_id)
    q = select(Workforce).where(Workforce.project_id == project_id)
    if kind:
        q = q.where(Workforce.kind == kind)
    return [_member_out(m) for m in (await db.execute(q.order_by(Workforce.name))).scalars()]


@router.post("/{project_id}/workforce", response_model=MemberDetail, status_code=201)
async def create_member(
    project_id: uuid.UUID,
    body: AgentCreateIn,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> MemberDetail:
    project = await _project(db, principal, project_id)
    config = body.config
    if config is not None and config.name != body.name:
        config = config.model_copy(update={"name": body.name})
    member = await svc.create_agent(db, principal, project, config=config, name=body.name, description=body.description)
    return await _detail(project, member)


async def _detail(project: Project, member: Workforce) -> MemberDetail:
    repo = svc.repo_for(project)
    filename = "agent.py" if member.kind == "agent" else "workflow.py"
    code = await repo.read_working(f"{member.path}/{filename}") or ""
    return MemberDetail(
        **_member_out(member).model_dump(), config=member.config_json, code=code, commit=await repo.head()
    )


@router.get("/{project_id}/workforce/{name}", response_model=MemberDetail)
async def get_member(
    project_id: uuid.UUID,
    name: str,
    principal: Principal = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> MemberDetail:
    project = await _project(db, principal, project_id)
    return await _detail(project, await svc.get_member(db, project, name))


@router.put("/{project_id}/workforce/{name}/config", response_model=MemberDetail)
async def put_config(
    project_id: uuid.UUID,
    name: str,
    body: AgentConfig,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> MemberDetail:
    project = await _project(db, principal, project_id)
    member = await svc.get_member(db, project, name)
    if member.kind != "agent":
        raise ApiError("Solo los agentes tienen configuración de Studio", code="not_an_agent")
    await svc.update_agent_config(db, principal, project, member, body)
    return await _detail(project, member)


@router.put("/{project_id}/workforce/{name}/code", response_model=MemberDetail)
async def put_code(
    project_id: uuid.UUID,
    name: str,
    body: CodeIn,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> MemberDetail:
    project = await _project(db, principal, project_id)
    member = await svc.get_member(db, project, name)
    if member.kind == "agent":
        await svc.update_agent_code(db, principal, project, member, body.code)
    else:
        from ..services import workflows as workflows_svc

        await workflows_svc.update_code(db, principal, project, member, body.code)
    return await _detail(project, member)


@router.delete("/{project_id}/workforce/{name}", status_code=204)
async def delete_member(
    project_id: uuid.UUID,
    name: str,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    project = await _project(db, principal, project_id)
    member = await svc.get_member(db, project, name)
    repo = svc.repo_for(project)
    author = await svc.author_for(db, principal)
    files = await repo.list_files("HEAD", prefix=f"{member.path}/")
    await repo.write(dict.fromkeys(files), message=f"Remove {member.name}", author=author.name, email=author.email)
    await db.delete(member)
    await audit.record(
        db,
        action="workforce.deleted",
        principal=principal,
        entity_type="workforce",
        entity_id=member.id,
        diff={"name": name},
    )
    return Response(status_code=204)


@router.get("/{project_id}/versions", response_model=list[VersionOut])
async def list_project_versions(
    project_id: uuid.UUID,
    principal: Principal = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> list[VersionOut]:
    """Project-level versions (snapshots used by deployments), newest first."""
    project = await _project(db, principal, project_id)
    rows = (
        await db.execute(
            select(Version)
            .where(Version.entity_type == "project", Version.entity_id == project.id)
            .order_by(Version.version.desc())
            .limit(200)
        )
    ).scalars()
    return [VersionOut.model_validate(v, from_attributes=True) for v in rows]


@router.get("/{project_id}/workforce/{name}/versions", response_model=list[VersionOut])
async def list_versions(
    project_id: uuid.UUID,
    name: str,
    principal: Principal = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> list[VersionOut]:
    project = await _project(db, principal, project_id)
    member = await svc.get_member(db, project, name)
    rows = (
        await db.execute(
            select(Version)
            .where(Version.entity_type == "workforce", Version.entity_id == member.id)
            .order_by(Version.version.desc())
        )
    ).scalars()
    return [VersionOut.model_validate(v, from_attributes=True) for v in rows]


@router.post("/{project_id}/workforce/{name}/versions", response_model=VersionOut, status_code=201)
async def save_version(
    project_id: uuid.UUID,
    name: str,
    body: VersionIn,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> VersionOut:
    project = await _project(db, principal, project_id)
    member = await svc.get_member(db, project, name)
    version = await svc.save_version(db, principal, project, member, body.message)
    return VersionOut.model_validate(version, from_attributes=True)


async def _version(db: AsyncSession, member: Workforce, number: int) -> Version:
    version = (
        await db.execute(
            select(Version).where(
                Version.entity_type == "workforce", Version.entity_id == member.id, Version.version == number
            )
        )
    ).scalar_one_or_none()
    if version is None:
        raise NotFound(f"No existe la versión {number}")
    return version


@router.get("/{project_id}/workforce/{name}/versions/{number}/diff")
async def diff_version(
    project_id: uuid.UUID,
    name: str,
    number: int,
    against: str = "HEAD",
    principal: Principal = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    project = await _project(db, principal, project_id)
    member = await svc.get_member(db, project, name)
    version = await _version(db, member, number)
    target = against
    if against.isdigit():
        target = (await _version(db, member, int(against))).git_commit
    diff = await svc.repo_for(project).diff(version.git_commit, target, member.path)
    return {"from": version.git_commit, "to": target, "diff": diff}


@router.post("/{project_id}/workforce/{name}/versions/{number}/restore", response_model=MemberDetail)
async def restore(
    project_id: uuid.UUID,
    name: str,
    number: int,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> MemberDetail:
    project = await _project(db, principal, project_id)
    member = await svc.get_member(db, project, name)
    await svc.restore_version(db, principal, project, member, await _version(db, member, number))
    return await _detail(project, member)


@router.get("/{project_id}/tools-catalog")
async def tools_catalog(
    project_id: uuid.UUID, principal: Principal = Depends(require_role("viewer")), db: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
    """Built-in tools available to agents (connector actions are listed by the connectors API)."""
    await _project(db, principal, project_id)
    return [{"key": key, **meta} for key, meta in BUILTIN_TOOLS.items()]


# ------------------------------------------------------------------------------------------- internal


@public_router.get("/internal/v1/projects/{project_id}/archive")
async def project_archive(
    project_id: uuid.UUID, ref: str = "HEAD", authorization: str = Header(default="")
) -> Response:
    """tar.gz of the project at ``ref`` for the data plane (service token, mTLS-ready)."""
    token = authorization.removeprefix("Bearer ").strip()
    if not token or not constant_time_equals(token, get_settings().service_token):
        raise Unauthorized("Token de servicio no válido", code="invalid_service_token")
    async with system_session() as s:
        project = await s.get(Project, project_id)
    if project is None:
        raise NotFound("Proyecto no encontrado")
    repo = ProjectRepo.for_project(str(project_id))
    try:
        commit = await repo.resolve(ref)
        data = await repo.archive(commit)
    except RepoError as exc:
        raise NotFound("Referencia no encontrada") from exc
    return Response(content=data, media_type="application/gzip", headers={"X-Messer-Commit": commit})
