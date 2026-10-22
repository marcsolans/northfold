"""/api/v1/templates — industry templates catalog (public) and cloning a template into a new project (builder)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db import Principal, system_session
from messer_common.db.models import Template

from ..deps import get_db, get_optional_principal, require_role
from ..errors import NotFound
from ..services import templates as svc
from ..services.templates_catalog import (
    OFFLINE_EVAL_TAG,
    SECTORS,
    LoadedTemplate,
    catalog_rows,
    match_scores,
    match_template,
)

router = APIRouter(prefix="/templates", tags=["templates"])


class TemplateCounts(BaseModel):
    agents: int
    workflows: int
    knowledge_bases: int
    documents: int
    tables: int
    interfaces: int
    channels: int
    evals: int


class TemplateOut(BaseModel):
    id: str
    sector: str
    name: str
    name_en: str
    description: str
    description_en: str
    tags: list[str]
    includes: list[str]
    includes_en: list[str]
    voice: bool
    approvals: bool
    counts: TemplateCounts
    sort_order: int
    updated_at: datetime


class TemplateDetailOut(TemplateOut):
    version: int
    default_model_tier: str
    agents: list[dict[str, Any]]
    workflows: list[dict[str, Any]]
    knowledge_bases: list[dict[str, Any]]
    interfaces: list[dict[str, Any]]
    channels: list[dict[str, Any]]
    phone: dict[str, Any] | None
    triggers: list[dict[str, Any]]
    requirements: list[dict[str, Any]]
    evals: list[dict[str, Any]]
    try_prompts: list[dict[str, Any]]
    plan: dict[str, Any]
    readme: str
    files: list[str]
    offline_eval_tag: str = OFFLINE_EVAL_TAG


class SectorOut(BaseModel):
    key: str
    count: int


class CatalogOut(BaseModel):
    items: list[TemplateOut]
    sectors: list[SectorOut]


class CloneIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class ClonedProjectOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str
    template_id: str | None


class CloneOut(BaseModel):
    project: ClonedProjectOut
    knowledge_bases: list[dict[str, Any]]
    members: list[dict[str, Any]]
    interfaces: list[str]
    channels: list[dict[str, Any]]
    triggers: list[dict[str, Any]]
    warnings: list[str]
    notes: list[dict[str, str]]
    url: str


class MatchOut(BaseModel):
    template_id: str | None
    scores: list[dict[str, Any]]


class ProjectRefOut(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime


def _counts(summary: dict[str, Any]) -> TemplateCounts:
    kbs = summary.get("knowledge_bases", [])
    return TemplateCounts(
        agents=len(summary.get("agents", [])),
        workflows=len(summary.get("workflows", [])),
        knowledge_bases=len(kbs),
        documents=sum(len(kb.get("documents", [])) for kb in kbs),
        tables=sum(len(kb.get("tables", [])) for kb in kbs),
        interfaces=len(summary.get("interfaces", [])),
        channels=len(summary.get("channels", [])) + (1 if summary.get("phone") else 0),
        evals=len(summary.get("evals", [])),
    )


def _out(row: Template, template: LoadedTemplate) -> TemplateOut:
    summary = template.summary
    return TemplateOut(
        id=row.id,
        sector=row.sector,
        name=row.name,
        name_en=row.name_en,
        description=row.description,
        description_en=row.description_en,
        tags=[str(t) for t in row.tags or []],
        includes=list(summary.get("includes", [])),
        includes_en=list(summary.get("includes_en", [])),
        voice=any(a.get("voice") for a in summary.get("agents", [])),
        approvals=any(w.get("approvals") for w in summary.get("workflows", []))
        or any(t.get("requires_approval") for a in summary.get("agents", []) for t in a.get("tools", [])),
        counts=_counts(summary),
        sort_order=row.sort_order,
        updated_at=row.updated_at,
    )


def _files(template: LoadedTemplate) -> list[str]:
    root = template.root
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts)


async def _row(template_id: str, principal: Principal | None) -> tuple[Template, LoadedTemplate]:
    template = svc.get_template(template_id)
    async with system_session() as s:
        row = await s.get(Template, template_id)
        if row is not None:
            s.expunge(row)
    if template is None or row is None or (not row.public and not (principal and principal.is_superadmin)):
        raise NotFound("Plantilla no encontrada", code="template_not_found")
    return row, template


@router.get("", response_model=CatalogOut)
async def list_templates(
    sector: str | None = Query(default=None, max_length=40),
    q: str | None = Query(default=None, max_length=200),
) -> CatalogOut:
    """Public catalog (also used by the website): published templates in display order."""
    async with system_session() as s:
        rows = await catalog_rows(s)
    loaded = {t.id: t for t in svc.all_templates()}
    items = [_out(r, loaded[r.id]) for r in rows]
    sectors = [SectorOut(key=k, count=sum(1 for i in items if i.sector == k)) for k in SECTORS]
    if sector:
        items = [i for i in items if i.sector == sector]
    if q and q.strip():
        needle = q.strip().lower()
        items = [
            i
            for i in items
            if needle in " ".join([i.name, i.name_en, i.description, i.description_en, *i.tags]).lower()
        ]
    return CatalogOut(items=items, sectors=[s for s in sectors if s.count])


@router.get("/match", response_model=MatchOut)
async def match(text: str = Query(min_length=3, max_length=4000)) -> MatchOut:
    """Template that best fits a free-text request (keyword match; what the Composer uses offline)."""
    return MatchOut(
        template_id=match_template(text),
        scores=[{"template_id": tid, "score": round(score, 2)} for tid, score in match_scores(text)[:5]],
    )


@router.get("/{template_id}", response_model=TemplateDetailOut)
async def get_template(
    template_id: str, principal: Principal | None = Depends(get_optional_principal)
) -> TemplateDetailOut:
    row, template = await _row(template_id, principal)
    summary = template.summary
    base = _out(row, template)
    return TemplateDetailOut(
        **base.model_dump(),
        version=int(summary.get("version", 1)),
        default_model_tier=str(summary.get("default_model_tier", "standard")),
        agents=list(summary.get("agents", [])),
        workflows=list(summary.get("workflows", [])),
        knowledge_bases=list(summary.get("knowledge_bases", [])),
        interfaces=list(summary.get("interfaces", [])),
        channels=list(summary.get("channels", [])),
        phone=summary.get("phone"),
        triggers=list(summary.get("triggers", [])),
        requirements=list(summary.get("requirements", [])),
        evals=list(summary.get("evals", [])),
        try_prompts=list(summary.get("try_prompts", [])),
        plan=template.plan.model_dump(mode="json"),
        readme=template.readme,
        files=_files(template),
    )


@router.get("/{template_id}/projects", response_model=list[ProjectRefOut])
async def template_projects(
    template_id: str,
    principal: Principal = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> list[ProjectRefOut]:
    """Projects of the active organization already created from this template."""
    await _row(template_id, principal)
    return [
        ProjectRefOut(id=p.id, name=p.name, created_at=p.created_at)
        for p in await svc.template_projects(db, template_id)
    ]


@router.post("/{template_id}/clone", response_model=CloneOut, status_code=201)
async def clone(template_id: str, body: CloneIn, principal: Principal = Depends(require_role("builder"))) -> CloneOut:
    """Create a new project from the template: agents, workflows, knowledge (sample documents and tables),
    interfaces, triggers and demo channels. Document ingestion continues in the background."""
    await _row(template_id, principal)
    result = await svc.clone_template(principal, template_id, name=body.name, description=body.description)
    project = result.project
    return CloneOut(
        project=ClonedProjectOut(
            id=project.id,
            name=project.name,
            slug=project.slug,
            description=project.description,
            template_id=project.template_id,
        ),
        knowledge_bases=result.knowledge_bases,
        members=result.members,
        interfaces=result.interfaces,
        channels=result.channels,
        triggers=result.triggers,
        warnings=result.warnings,
        notes=result.notes,
        url=f"/app/projects/{project.id}",
    )
