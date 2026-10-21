"""Projects and workforce members backed by a git repository per project."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

import yaml
from slugify import slugify
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common.db import Principal
from messer_common.db.models import Environment, Org, Plan, Project, User, Version, Workforce
from messer_common.plans import limit_value
from messer_common.projects_repo import ProjectRepo
from messer_common.studio.agent_spec import (
    AgentConfig,
    ContextFile,
    default_agent_config,
    parse_agent_code,
    render_agent_code,
)
from messer_common.studio.project_files import agent_member_files, initial_project_files, member_manifest

from ..errors import ApiError, Conflict, NotFound, PlanLimitExceeded

ENVIRONMENTS = ("development", "production")


@dataclass(slots=True)
class Author:
    name: str
    email: str


async def author_for(session: AsyncSession, principal: Principal) -> Author:
    if principal.user_id:
        user = await session.get(User, principal.user_id)
        if user is not None:
            return Author(name=user.name or user.email, email=user.email)
    return Author(name="Messer API", email="api@messer.local")


async def _check_project_capacity(session: AsyncSession, org_id: uuid.UUID) -> None:
    org = await session.get(Org, org_id)
    plan = await session.get(Plan, org.plan_id) if org and org.plan_id else None
    if plan is None:
        return
    limit = limit_value(plan.limits, "projects")
    if limit == -1:
        return
    used = int(
        (
            await session.execute(
                select(func.count()).select_from(Project).where(Project.org_id == org_id, Project.archived_at.is_(None))
            )
        ).scalar_one()
    )
    if used >= limit:
        raise PlanLimitExceeded(
            f"Tu plan {plan.name} incluye {limit} proyecto(s). Mejora el plan para crear más.",
            details={"limit": "projects", "value": limit, "used": used},
        )


async def _unique_project_slug(session: AsyncSession, org_id: uuid.UUID, name: str) -> str:
    base = slugify(name, max_length=60) or "proyecto"
    slug, n = base, 2
    while (
        await session.execute(select(Project.id).where(Project.org_id == org_id, Project.slug == slug))
    ).first() is not None:
        slug = f"{base}-{n}"
        n += 1
    return slug


async def create_project(
    session: AsyncSession,
    principal: Principal,
    *,
    name: str,
    description: str = "",
    default_model_tier: str = "standard",
    template_id: str | None = None,
    files: dict[str, str] | None = None,
) -> Project:
    assert principal.org_id is not None
    await _check_project_capacity(session, principal.org_id)
    project_id = uuid.uuid4()
    repo = ProjectRepo.for_project(str(project_id))
    project = Project(
        id=project_id,
        org_id=principal.org_id,
        name=name.strip(),
        slug=await _unique_project_slug(session, principal.org_id, name),
        description=description,
        repo_path=str(repo.path),
        default_model_tier=default_model_tier,
        template_id=template_id,
        created_by=principal.user_id,
    )
    session.add(project)
    await session.flush()
    for env_name in ENVIRONMENTS:
        session.add(Environment(org_id=principal.org_id, project_id=project_id, name=env_name))
    author = await author_for(session, principal)
    content = initial_project_files(
        project_id=str(project_id), name=project.name, description=description, default_tier=default_model_tier
    )
    if files:
        content.update(files)
    await repo.init(content, message=f"Create project {project.name}", author=author.name, email=author.email)
    await audit.record(
        session,
        action="project.created",
        principal=principal,
        entity_type="project",
        entity_id=project_id,
        diff={"name": project.name, "template_id": template_id},
    )
    return project


async def get_project(session: AsyncSession, project_id: uuid.UUID) -> Project:
    project = await session.get(Project, project_id)
    if project is None or project.archived_at is not None:
        raise NotFound("Proyecto no encontrado")
    return project


def repo_for(project: Project) -> ProjectRepo:
    return ProjectRepo.for_project(str(project.id))


async def update_manifest(
    session: AsyncSession, principal: Principal, project: Project, changes: dict[str, Any]
) -> str:
    repo = repo_for(project)
    raw = await repo.read_working("messer.project.yaml") or ""
    manifest = yaml.safe_load(raw) or {}
    manifest.update(changes)
    author = await author_for(session, principal)
    return await repo.write(
        {
            "messer.project.yaml": "# Messer project manifest\n"
            + yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False)
        },
        message="Update project settings",
        author=author.name,
        email=author.email,
    )


# ------------------------------------------------------------------------------------------- workforce


async def get_member(session: AsyncSession, project: Project, name: str) -> Workforce:
    member = (
        await session.execute(select(Workforce).where(Workforce.project_id == project.id, Workforce.name == name))
    ).scalar_one_or_none()
    if member is None:
        raise NotFound(f"No existe «{name}» en este proyecto")
    return member


async def create_agent(
    session: AsyncSession,
    principal: Principal,
    project: Project,
    *,
    config: AgentConfig | None = None,
    name: str | None = None,
    description: str = "",
    message: str | None = None,
) -> Workforce:
    cfg = config or default_agent_config(name or "agente", description)
    if cfg.model_tier is None and cfg.model is None:
        cfg.model_tier = project.default_model_tier  # type: ignore[assignment]
    exists = (
        await session.execute(
            select(Workforce.id).where(Workforce.project_id == project.id, Workforce.name == cfg.name)
        )
    ).first()
    if exists is not None:
        raise Conflict(f"Ya existe «{cfg.name}» en este proyecto", code="name_taken")
    member = Workforce(
        org_id=project.org_id,
        project_id=project.id,
        kind="agent",
        name=cfg.name,
        description=cfg.description,
        path=f"workforce/{cfg.name}",
        config_json=cfg.model_dump(mode="json"),
        source_mode="config",
    )
    session.add(member)
    await session.flush()
    author = await author_for(session, principal)
    await repo_for(project).write(
        agent_member_files(member_id=str(member.id), config=cfg),
        message=message or f"Add agent {cfg.name}",
        author=author.name,
        email=author.email,
    )
    await audit.record(
        session,
        action="workforce.created",
        principal=principal,
        entity_type="workforce",
        entity_id=member.id,
        diff={"name": cfg.name, "kind": "agent"},
    )
    return member


async def update_agent_config(
    session: AsyncSession, principal: Principal, project: Project, member: Workforce, config: AgentConfig
) -> str:
    if config.name != member.name:
        raise ApiError("El nombre de un agente no se puede cambiar; duplica el agente", code="rename_unsupported")
    repo = repo_for(project)
    author = await author_for(session, principal)
    files = {
        f"{member.path}/agent.py": render_agent_code(config),
        f"{member.path}/messer.yaml": member_manifest(
            member_id=str(member.id), kind="agent", source_mode="config", config=config.model_dump(mode="json")
        ),
    }
    commit = await repo.write(
        files, message=f"Update {member.name} configuration", author=author.name, email=author.email
    )
    member.config_json = config.model_dump(mode="json")
    member.description = config.description
    member.source_mode = "config"
    return commit


async def update_agent_code(
    session: AsyncSession, principal: Principal, project: Project, member: Workforce, code: str
) -> tuple[str, str]:
    """Write hand-edited code. Returns (commit, source_mode). Config follows the code when parseable."""
    try:
        compile(code, f"{member.path}/agent.py", "exec")
    except SyntaxError as exc:
        raise ApiError(
            f"Error de sintaxis en la línea {exc.lineno}: {exc.msg}",
            code="syntax_error",
            details={"line": exc.lineno, "offset": exc.offset},
        ) from exc
    parsed = parse_agent_code(code)
    source_mode = "config" if parsed is not None and parsed.name == member.name else "code"
    config_json = parsed.model_dump(mode="json") if parsed is not None and source_mode == "config" else None
    author = await author_for(session, principal)
    commit = await repo_for(project).write(
        {
            f"{member.path}/agent.py": code,
            f"{member.path}/messer.yaml": member_manifest(
                member_id=str(member.id),
                kind=member.kind,
                source_mode=source_mode,
                config=config_json if config_json is not None else member.config_json,
            ),
        },
        message=f"Edit {member.name} code",
        author=author.name,
        email=author.email,
    )
    member.source_mode = source_mode
    if config_json is not None:
        member.config_json = config_json
    return commit, source_mode


async def save_version(
    session: AsyncSession, principal: Principal, project: Project, member: Workforce, message: str
) -> Version:
    repo = repo_for(project)
    commit = await repo.head()
    code = await repo.read(f"{member.path}/{'agent.py' if member.kind == 'agent' else 'workflow.py'}", commit) or ""
    number = member.current_version + 1
    version = Version(
        org_id=project.org_id,
        project_id=project.id,
        entity_type="workforce",
        entity_id=member.id,
        version=number,
        git_commit=commit,
        snapshot_json={"config": member.config_json, "code": code, "source_mode": member.source_mode},
        author_id=principal.user_id,
        message=message or f"Versión {number}",
    )
    session.add(version)
    member.current_version = number
    await session.flush()
    await audit.record(
        session,
        action="workforce.version_saved",
        principal=principal,
        entity_type="workforce",
        entity_id=member.id,
        diff={"version": number, "commit": commit},
    )
    return version


async def project_version(session: AsyncSession, principal: Principal, project: Project, message: str) -> Version:
    """Snapshot of the whole project (used by deployments)."""
    repo = repo_for(project)
    commit = await repo.head()
    last = (
        await session.execute(
            select(func.max(Version.version)).where(Version.entity_type == "project", Version.entity_id == project.id)
        )
    ).scalar_one()
    number = int(last or 0) + 1
    version = Version(
        org_id=project.org_id,
        project_id=project.id,
        entity_type="project",
        entity_id=project.id,
        version=number,
        git_commit=commit,
        snapshot_json={"files": await repo.list_files(commit)},
        author_id=principal.user_id,
        message=message or f"Versión {number}",
    )
    session.add(version)
    await session.flush()
    return version


async def restore_version(
    session: AsyncSession, principal: Principal, project: Project, member: Workforce, version: Version
) -> str:
    author = await author_for(session, principal)
    commit = await repo_for(project).restore(
        [member.path],
        version.git_commit,
        message=f"Restore {member.name} to v{version.version}",
        author=author.name,
        email=author.email,
    )
    snapshot = version.snapshot_json or {}
    if snapshot.get("config") is not None:
        member.config_json = snapshot["config"]
    member.source_mode = snapshot.get("source_mode", member.source_mode)
    await audit.record(
        session,
        action="workforce.version_restored",
        principal=principal,
        entity_type="workforce",
        entity_id=member.id,
        diff={"version": version.version},
    )
    return commit


# ------------------------------------------------------------------------------------------ context files

CONTEXT_FILE_MAX_BYTES = 5 * 1024 * 1024
CONTEXT_FILE_SUFFIXES = (".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".xml", ".tsv", ".html", ".pdf", ".docx")
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str) -> str:
    base = _SAFE_FILENAME.sub("_", name.strip().replace("\\", "/").rsplit("/", 1)[-1]).strip("._")
    return base[:120] or "archivo"


async def add_context_file(
    session: AsyncSession,
    principal: Principal,
    project: Project,
    member: Workforce,
    *,
    filename: str,
    data: bytes,
    mime: str,
) -> ContextFile:
    name = safe_filename(filename)
    if not name.lower().endswith(CONTEXT_FILE_SUFFIXES):
        raise ApiError(
            "Formato no admitido para archivos de contexto",
            code="unsupported_file",
            details={"allowed": list(CONTEXT_FILE_SUFFIXES)},
        )
    if len(data) > CONTEXT_FILE_MAX_BYTES:
        raise ApiError("El archivo supera 5 MB", code="file_too_large", status_code=413)
    entry = ContextFile(name=name, mime=mime or "application/octet-stream", size=len(data))
    author = await author_for(session, principal)
    files: dict[str, str | bytes | None] = {f"{member.path}/context/{name}": data}
    if member.source_mode == "config":
        config = AgentConfig.model_validate(member.config_json)
        config.context_files = [c for c in config.context_files if c.name != name] + [entry]
        files[f"{member.path}/agent.py"] = render_agent_code(config)
        files[f"{member.path}/messer.yaml"] = member_manifest(
            member_id=str(member.id), kind=member.kind, source_mode="config", config=config.model_dump(mode="json")
        )
        member.config_json = config.model_dump(mode="json")
    await repo_for(project).write(
        files, message=f"Add context file {name} to {member.name}", author=author.name, email=author.email
    )
    await audit.record(
        session,
        action="workforce.context_file_added",
        principal=principal,
        entity_type="workforce",
        entity_id=member.id,
        diff={"file": name, "size": len(data)},
    )
    return entry


async def remove_context_file(
    session: AsyncSession, principal: Principal, project: Project, member: Workforce, name: str
) -> None:
    author = await author_for(session, principal)
    files: dict[str, str | bytes | None] = {f"{member.path}/context/{safe_filename(name)}": None}
    if member.source_mode == "config":
        config = AgentConfig.model_validate(member.config_json)
        config.context_files = [c for c in config.context_files if c.name != name]
        files[f"{member.path}/agent.py"] = render_agent_code(config)
        files[f"{member.path}/messer.yaml"] = member_manifest(
            member_id=str(member.id), kind=member.kind, source_mode="config", config=config.model_dump(mode="json")
        )
        member.config_json = config.model_dump(mode="json")
    await repo_for(project).write(
        files, message=f"Remove context file {name} from {member.name}", author=author.name, email=author.email
    )
    await audit.record(
        session,
        action="workforce.context_file_removed",
        principal=principal,
        entity_type="workforce",
        entity_id=member.id,
        diff={"file": name},
    )
