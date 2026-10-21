"""One-click deployment: version → evals gate → point the environment at the version → warm the runtime.

The pipeline runs in the worker (``Jobs.DEPLOY``); every step appends to ``deployments.logs`` so the UI can show
progress. Runs already in flight keep executing on the previous commit's sandbox; new runs use the new commit.
"""

from __future__ import annotations

import importlib
import uuid
from datetime import UTC, datetime
from typing import Any

import yaml
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit, runtime_client
from messer_common.db import Principal, system_session
from messer_common.db.models import (
    Deployment,
    Environment,
    EvalRun,
    Membership,
    Notification,
    Org,
    Project,
    User,
    Version,
    Workforce,
)
from messer_common.email import send_template
from messer_common.logging import get_logger
from messer_common.projects_repo import ProjectRepo
from messer_common.queue import Jobs, enqueue
from messer_common.roles import at_least
from messer_common.runtime_client import RuntimeUnavailable
from messer_common.settings import get_settings

from ..errors import ApiError, Forbidden, NotFound
from . import projects as project_svc

log = get_logger("messer.deployments")

ACTIVE = ("pending", "evaluating", "deploying")


def _log(deployment: Deployment, message: str, level: str = "info", **data: Any) -> None:
    entry = {"at": datetime.now(UTC).isoformat(), "level": level, "message": message, **data}
    deployment.logs = [*list(deployment.logs or []), entry]


def environment_url(org: Org, project: Project, env: Environment) -> str:
    if env.custom_domain and env.domain_status == "active":
        return f"https://{env.custom_domain}"
    base = get_settings().messer_web_url.rstrip("/")
    suffix = "" if env.name == "production" else "?env=development"
    return f"{base}/{org.slug}/{project.slug}{suffix}"


async def get_environment(session: AsyncSession, project_id: uuid.UUID, name: str) -> Environment:
    env = (
        await session.execute(select(Environment).where(Environment.project_id == project_id, Environment.name == name))
    ).scalar_one_or_none()
    if env is None:
        raise NotFound("Entorno no encontrado")
    return env


async def request_deployment(
    session: AsyncSession,
    principal: Principal,
    project: Project,
    *,
    environment: str,
    version_id: uuid.UUID | None,
    force: bool,
    message: str = "",
    skip_evals: bool = False,
) -> Deployment:
    """Create the deployment row and queue the pipeline. ``force`` (skip a failing gate) is admin-only."""
    if force and not (principal.is_superadmin or at_least(principal.role, "admin")):
        raise Forbidden("Solo un administrador puede forzar un despliegue", code="force_requires_admin")
    env = await get_environment(session, project.id, environment)
    busy = (
        await session.execute(
            select(Deployment.id).where(Deployment.environment_id == env.id, Deployment.status.in_(ACTIVE))
        )
    ).first()
    if busy is not None:
        raise ApiError("Ya hay un despliegue en curso en este entorno", code="deployment_in_progress", status_code=409)
    if version_id is None:
        version = await project_svc.project_version(session, principal, project, message or "Publicación")
    else:
        version = await session.get(Version, version_id)
        if version is None or version.project_id != project.id:
            raise NotFound("Versión no encontrada")
    deployment = Deployment(
        org_id=project.org_id,
        environment_id=env.id,
        project_id=project.id,
        version_id=version.id,
        status="pending",
        created_by=principal.user_id,
        forced_by=principal.user_id if force else None,
    )
    _log(
        deployment,
        f"Despliegue solicitado: versión {version.version} ({version.git_commit[:8]}) → {environment}",
        force=force,
        skip_evals=skip_evals,
    )
    session.add(deployment)
    await session.flush()
    await audit.record(
        session,
        action="deployment.forced" if force else "deployment.requested",
        principal=principal,
        entity_type="deployment",
        entity_id=deployment.id,
        diff={
            "environment": environment,
            "version": version.version,
            "commit": version.git_commit,
            "skip_evals": skip_evals,
        },
    )
    await enqueue(Jobs.DEPLOY, str(deployment.id), force, skip_evals, _job_id=f"deploy:{deployment.id}")
    return deployment


async def _members_at(repo: ProjectRepo, commit: str) -> list[str]:
    names: list[str] = []
    for path in await repo.list_files(commit):
        parts = path.split("/")
        if len(parts) == 3 and parts[0] == "workforce" and parts[2] == "messer.yaml":
            names.append(parts[1])
    return sorted(names)


async def _has_evals(repo: ProjectRepo, commit: str, name: str) -> bool:
    files = await repo.list_files(commit)
    return any(f.startswith(f"workforce/{name}/evals/") and f.endswith((".yaml", ".yml")) for f in files)


async def _member_kind(repo: ProjectRepo, commit: str, name: str) -> str:
    raw = await repo.read(f"workforce/{name}/messer.yaml", commit)
    return str((yaml.safe_load(raw or "") or {}).get("_type", "agent"))


async def run_pipeline(deployment_id: uuid.UUID, *, force: bool = False, skip_evals: bool = False) -> Deployment:
    """Execute a queued deployment (called by the worker job)."""
    async with system_session() as s:
        dep = await s.get(Deployment, deployment_id, with_for_update=True)
        if dep is None:
            raise LookupError("deployment not found")
        if dep.status not in ("pending",):
            return dep
        dep.status = "evaluating"
        version = await s.get(Version, dep.version_id)
        project = await s.get(Project, dep.project_id)
        assert version is not None and project is not None
        commit, project_id, org_id = version.git_commit, project.id, project.org_id
    repo = ProjectRepo.for_project(str(project_id))
    failures: list[str] = []
    gate_logs: list[tuple[str, str, dict[str, Any]]] = []
    eval_ids: list[uuid.UUID] = []
    if skip_evals:
        gate_logs.append(("Evals omitidas (reversión a una versión ya publicada)", "warning", {}))
    else:
        for name in await _members_at(repo, commit):
            if not await _has_evals(repo, commit, name):
                gate_logs.append((f"{name}: sin evals", "warning", {"member": name}))
                continue
            try:
                result = await runtime_client.evals(project_id, name, ref=commit)
            except RuntimeUnavailable as exc:
                result = {
                    "passed": 0,
                    "failed": 1,
                    "results": [],
                    "error": {"type": "runtime_unavailable", "message": str(exc)[:500]},
                }
            failed = int(result.get("failed") or 0) + (1 if result.get("error") else 0)
            passed = int(result.get("passed") or 0)
            async with system_session() as s:
                member = (
                    await s.execute(select(Workforce).where(Workforce.project_id == project_id, Workforce.name == name))
                ).scalar_one_or_none()
                ev = EvalRun(
                    org_id=org_id,
                    project_id=project_id,
                    workforce_id=member.id if member else None,
                    version_id=version.id,
                    trigger="deploy",
                    status="failed" if failed else "passed",
                    passed=passed,
                    failed=failed,
                    results=list(result.get("results") or [])
                    + ([{"error": result["error"]}] if result.get("error") else []),
                    finished_at=datetime.now(UTC),
                )
                s.add(ev)
                await s.flush()
                eval_ids.append(ev.id)
            level = "error" if failed else "info"
            gate_logs.append(
                (
                    f"{name}: evals {passed} correctas, {failed} fallidas",
                    level,
                    {"member": name, "passed": passed, "failed": failed},
                )
            )
            if failed:
                failures.append(name)
    async with system_session() as s:
        dep = await s.get(Deployment, deployment_id, with_for_update=True)
        assert dep is not None
        for message, level, data in gate_logs:
            _log(dep, message, level, **data)
        dep.eval_run_id = eval_ids[0] if eval_ids else None
        if failures and not force:
            dep.status = "failed"
            dep.finished_at = datetime.now(UTC)
            _log(dep, f"La puerta de evals ha bloqueado el despliegue ({', '.join(failures)})", "error")
            await _notify_failure(s, dep, failures)
            return dep
        if failures:
            _log(dep, "Puerta de evals fallida: despliegue forzado por un administrador", "warning")
        dep.status = "deploying"
        _log(dep, "Preparando el entorno de ejecución")
    try:
        await runtime_client.warm(project_id, commit)
        warm_note: tuple[str, str] = ("Entorno de ejecución listo", "info")
    except RuntimeUnavailable as exc:
        warm_note = (
            f"No se pudo precalentar el entorno de ejecución ({exc}); se preparará en la primera ejecución",
            "warning",
        )
    async with system_session() as s:
        dep = await s.get(Deployment, deployment_id, with_for_update=True)
        assert dep is not None
        _log(dep, *warm_note)
        env = await s.get(Environment, dep.environment_id, with_for_update=True)
        org = await s.get(Org, org_id)
        project = await s.get(Project, project_id)
        assert env is not None and org is not None and project is not None
        await s.execute(
            update(Deployment)
            .where(Deployment.environment_id == env.id, Deployment.status == "live", Deployment.id != dep.id)
            .values(status="superseded")
        )
        env.deployed_version_id = dep.version_id
        env.status = "live"
        env.url = environment_url(org, project, env)
        await _publish_interfaces(s, project, commit, env.name, dep)
        dep.status = "live"
        dep.finished_at = datetime.now(UTC)
        _log(dep, f"Publicado en {env.name}: {env.url}")
        await audit.record(
            s,
            action="deployment.live",
            org_id=org_id,
            entity_type="deployment",
            entity_id=dep.id,
            diff={"environment": env.name, "commit": commit, "forced": bool(dep.forced_by)},
        )
    log.info("deployment.live", deployment_id=str(deployment_id), commit=commit[:8])
    return dep


async def _publish_interfaces(
    session: AsyncSession, project: Project, commit: str, environment: str, dep: Deployment
) -> None:
    """Snapshot the project's interfaces at the deployed commit (provided by the interfaces service)."""
    try:
        interfaces_svc = importlib.import_module("messer_api.services.interfaces")
    except ModuleNotFoundError:
        return
    publish = getattr(interfaces_svc, "publish_for_deployment", None)
    if publish is None:
        return
    await publish(session, project, commit, environment)
    _log(dep, "Interfaces publicadas")


async def _notify_failure(session: AsyncSession, dep: Deployment, failures: list[str]) -> None:
    project = await session.get(Project, dep.project_id)
    env = await session.get(Environment, dep.environment_id)
    rows = (
        await session.execute(
            select(Membership, User).join(User, User.id == Membership.user_id).where(Membership.org_id == dep.org_id)
        )
    ).all()
    url = f"{get_settings().messer_web_url.rstrip('/')}/app/projects/{dep.project_id}/deployments"
    for membership, user in rows:
        if not at_least(membership.role, "builder") and user.id != dep.created_by:
            continue
        session.add(
            Notification(
                org_id=dep.org_id,
                user_id=user.id,
                kind="deployment_failed",
                payload={
                    "title": f"Despliegue bloqueado: {project.name if project else ''}",
                    "body": f"Evals fallidas en {', '.join(failures)}",
                    "url": url,
                },
            )
        )
        if user.id == dep.created_by:
            await send_template(
                user.email,
                "deployment_failed",
                {
                    "project": project.name if project else "",
                    "environment": env.name if env else "",
                    "reason": f"evals fallidas en {', '.join(failures)}",
                    "url": url,
                },
                user.locale or "es",
            )


async def rollback(session: AsyncSession, principal: Principal, deployment: Deployment) -> Deployment:
    """Deploy again the version of a previous deployment (it already passed its gate when it went live)."""
    if deployment.status not in ("live", "superseded"):
        raise ApiError("Solo se puede volver a una versión que estuvo publicada", code="not_rollbackable")
    project = await project_svc.get_project(session, deployment.project_id)
    env = await session.get(Environment, deployment.environment_id)
    assert env is not None
    return await request_deployment(
        session,
        principal,
        project,
        environment=env.name,
        version_id=deployment.version_id,
        force=False,
        message="Reversión",
        skip_evals=True,
    )
