"""Deployments (publish, history, roll back) and custom domains per environment."""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import datetime
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common.db import Principal, system_session
from messer_common.db.models import Deployment, Environment, Interface, Org, Project, Version
from messer_common.settings import get_settings

from ..deps import ensure_project_access, get_db, require_role
from ..errors import ApiError, NotFound
from ..services import deployments as svc
from ..services import projects as project_svc

router = APIRouter(tags=["deployments"])
public_router = APIRouter(tags=["deployments"])

# Test hook: DNS-over-HTTPS transport.
dns_transport: httpx.AsyncBaseTransport | None = None
DOH_URL = "https://cloudflare-dns.com/dns-query"
_DOMAIN = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


class DeploymentOut(BaseModel):
    id: uuid.UUID
    environment: str
    version_id: uuid.UUID
    version: int | None
    git_commit: str | None
    message: str | None
    status: str
    logs: list[dict[str, Any]]
    eval_run_id: uuid.UUID | None
    forced: bool
    created_by: uuid.UUID | None
    created_at: datetime
    finished_at: datetime | None


async def _out(session: AsyncSession, dep: Deployment) -> DeploymentOut:
    env = await session.get(Environment, dep.environment_id)
    version = await session.get(Version, dep.version_id)
    return DeploymentOut(
        id=dep.id,
        environment=env.name if env else "",
        version_id=dep.version_id,
        version=version.version if version else None,
        git_commit=version.git_commit if version else None,
        message=version.message if version else None,
        status=dep.status,
        logs=list(dep.logs or []),
        eval_run_id=dep.eval_run_id,
        forced=dep.forced_by is not None,
        created_by=dep.created_by,
        created_at=dep.created_at,
        finished_at=dep.finished_at,
    )


class DeployIn(BaseModel):
    environment: Literal["development", "production"] = "production"
    version_id: uuid.UUID | None = None
    force: bool = False
    message: str = Field(default="", max_length=500)


@router.post("/projects/{project_id}/deployments", response_model=DeploymentOut, status_code=202)
async def deploy(
    project_id: uuid.UUID,
    body: DeployIn,
    principal: Principal = Depends(require_role("builder")),
    session: AsyncSession = Depends(get_db),
) -> DeploymentOut:
    """Publish a version (or a snapshot of the latest code). Evals act as a gate; admins may force."""
    ensure_project_access(principal, project_id)
    project = await project_svc.get_project(session, project_id)
    async with system_session() as owner:
        # The deployment row and audit entry are written with the owner role so the worker sees them at once.
        project_row = await owner.get(Project, project.id)
        assert project_row is not None
        dep = await svc.request_deployment(
            owner,
            principal,
            project_row,
            environment=body.environment,
            version_id=body.version_id,
            force=body.force,
            message=body.message,
        )
        return await _out(owner, dep)


@router.get("/projects/{project_id}/deployments", response_model=list[DeploymentOut])
async def history(
    project_id: uuid.UUID,
    principal: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db),
    environment: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[DeploymentOut]:
    ensure_project_access(principal, project_id)
    q = select(Deployment).where(Deployment.project_id == project_id)
    if environment:
        env = await svc.get_environment(session, project_id, environment)
        q = q.where(Deployment.environment_id == env.id)
    rows = (await session.execute(q.order_by(Deployment.created_at.desc()).limit(limit))).scalars().all()
    return [await _out(session, d) for d in rows]


async def _get(session: AsyncSession, principal: Principal, deployment_id: uuid.UUID) -> Deployment:
    dep = await session.get(Deployment, deployment_id)
    if dep is None or dep.org_id != principal.org_id:
        raise NotFound("Despliegue no encontrado")
    ensure_project_access(principal, dep.project_id)
    return dep


@router.get("/deployments/{deployment_id}", response_model=DeploymentOut)
async def get_deployment(
    deployment_id: uuid.UUID,
    principal: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db),
) -> DeploymentOut:
    return await _out(session, await _get(session, principal, deployment_id))


@router.post("/deployments/{deployment_id}/rollback", response_model=DeploymentOut, status_code=202)
async def rollback(
    deployment_id: uuid.UUID,
    principal: Principal = Depends(require_role("builder")),
    session: AsyncSession = Depends(get_db),
) -> DeploymentOut:
    await _get(session, principal, deployment_id)
    async with system_session() as owner:
        dep = await owner.get(Deployment, deployment_id)
        assert dep is not None
        new = await svc.rollback(owner, principal, dep)
        return await _out(owner, new)


# ------------------------------------------------------------------------------------------- domains


class DomainIn(BaseModel):
    domain: str = Field(min_length=4, max_length=253)


def _domain_view(env: Environment) -> dict[str, Any]:
    s = get_settings()
    return {
        "environment": env.name,
        "domain": env.custom_domain,
        "status": env.domain_status,
        "dns": [
            {"type": "CNAME", "name": env.custom_domain, "value": s.messer_cname_target},
            {"type": "TXT", "name": f"_messer-verify.{env.custom_domain}", "value": env.domain_verification_token},
        ]
        if env.custom_domain
        else [],
        "url": env.url,
    }


@router.put("/projects/{project_id}/environments/{name}/domain")
async def set_domain(
    project_id: uuid.UUID,
    name: str,
    body: DomainIn,
    principal: Principal = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    ensure_project_access(principal, project_id)
    domain = body.domain.strip().lower().rstrip(".")
    if not _DOMAIN.match(domain) or domain.endswith(f".{get_settings().messer_root_domain}"):
        raise ApiError("Dominio no válido", code="invalid_domain")
    env = await svc.get_environment(session, project_id, name)
    taken = (
        await session.execute(
            select(Environment.id).where(Environment.custom_domain == domain, Environment.id != env.id)
        )
    ).first()
    if taken is not None:
        raise ApiError("Ese dominio ya está en uso", code="domain_taken", status_code=409)
    env.custom_domain = domain
    env.domain_status = "pending"
    env.domain_verification_token = f"messer-verify={secrets.token_hex(16)}"
    await audit.record(
        session,
        action="domain.set",
        principal=principal,
        entity_type="environment",
        entity_id=env.id,
        diff={"domain": domain},
    )
    return _domain_view(env)


async def _dns_records(name: str, rtype: str) -> list[str]:
    async with httpx.AsyncClient(timeout=10, transport=dns_transport) as c:
        res = await c.get(DOH_URL, params={"name": name, "type": rtype}, headers={"accept": "application/dns-json"})
    if res.status_code != 200:
        return []
    return [str(a.get("data", "")).strip('"').rstrip(".").lower() for a in (res.json().get("Answer") or [])]


@router.post("/projects/{project_id}/environments/{name}/domain/verify")
async def verify_domain(
    project_id: uuid.UUID,
    name: str,
    principal: Principal = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Check the TXT ownership record and the CNAME; once both match the domain becomes active."""
    ensure_project_access(principal, project_id)
    env = await svc.get_environment(session, project_id, name)
    if not env.custom_domain:
        raise ApiError("No hay dominio configurado", code="no_domain")
    try:
        txt = await _dns_records(f"_messer-verify.{env.custom_domain}", "TXT")
        cname = await _dns_records(env.custom_domain, "CNAME")
    except httpx.HTTPError as exc:
        raise ApiError(
            "No se pudo consultar el DNS; inténtalo de nuevo", code="dns_unavailable", status_code=503
        ) from exc
    token_ok = (env.domain_verification_token or "").lower() in txt
    target = get_settings().messer_cname_target.lower().rstrip(".")
    cname_ok = target in cname
    if token_ok and cname_ok:
        env.domain_status = "active"
        project = await session.get(Project, env.project_id)
        org = await session.get(Org, env.org_id)
        if project is not None and org is not None:
            env.url = svc.environment_url(org, project, env)
        await audit.record(
            session,
            action="domain.verified",
            principal=principal,
            entity_type="environment",
            entity_id=env.id,
            diff={"domain": env.custom_domain},
        )
    elif token_ok:
        env.domain_status = "verified"
    view = _domain_view(env)
    view["checks"] = {"txt": token_ok, "cname": cname_ok}
    return view


@router.delete("/projects/{project_id}/environments/{name}/domain", status_code=204)
async def remove_domain(
    project_id: uuid.UUID,
    name: str,
    principal: Principal = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_db),
) -> None:
    ensure_project_access(principal, project_id)
    env = await svc.get_environment(session, project_id, name)
    await audit.record(
        session,
        action="domain.removed",
        principal=principal,
        entity_type="environment",
        entity_id=env.id,
        diff={"domain": env.custom_domain},
    )
    env.custom_domain = None
    env.domain_status = None
    env.domain_verification_token = None


@public_router.get("/api/internal/domains/allowed")
async def domain_allowed(domain: str) -> Response:
    """On-demand TLS ``ask`` endpoint for the edge proxy (Caddy): 200 only for active custom domains."""
    async with system_session() as s:
        env = (
            await s.execute(
                select(Environment).where(
                    Environment.custom_domain == domain.lower(), Environment.domain_status == "active"
                )
            )
        ).scalar_one_or_none()
    return Response(status_code=200 if env is not None else 404)


@public_router.get("/api/public/v1/domains/resolve")
async def resolve_domain(host: str) -> dict[str, Any]:
    """Map a custom domain to its organization/project/environment (used by the web edge for rewrites)."""
    async with system_session() as s:
        env = (
            await s.execute(
                select(Environment).where(
                    Environment.custom_domain == host.lower().split(":")[0], Environment.domain_status == "active"
                )
            )
        ).scalar_one_or_none()
        if env is None:
            raise NotFound("Dominio desconocido")
        project = await s.get(Project, env.project_id)
        org = await s.get(Org, env.org_id)
        if project is None or org is None:
            raise NotFound("Dominio desconocido")
        # The domain root opens the project's first published interface (app before chat).
        home = (
            await s.execute(
                select(Interface.kind, Interface.slug, Interface.workforce_name)
                .where(Interface.project_id == project.id, Interface.published_at.is_not(None))
                .order_by(Interface.kind, Interface.published_at)
                .limit(1)
            )
        ).first()
        home_path = None
        if home is not None:
            home_path = f"/app/{home.slug}" if home.kind == "app" else f"/chat/{home.workforce_name or home.slug}"
        return {"org": org.slug, "project": project.slug, "environment": env.name, "home": home_path}
