"""Knowledge base lifecycle: create (schema, reader role, views, vector index), update, delete."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db import Principal, system_session
from messer_common.db.models import KbBackup, KbChunk, KbFile, KbTable, KnowledgeBase, Org, Project
from messer_common.knowledge.embeddings import (
    LOCAL_DEFAULT_MODEL,
    VOYAGE_PREFIX,
    default_embedding_model,
    local_model_available,
    model_dim,
)
from messer_common.knowledge.errors import EmbeddingUnavailable, KnowledgeError
from messer_common.knowledge.policies import GOVERNANCE_MODES

from .common import publish_kb_event, record_audit
from .files import delete_blobs
from .provisioning import deprovision, drop_vector_index, ensure_vector_index, new_kb_identifiers, provision


async def resolve_embedding_model(org: Org, requested: str | None) -> tuple[str, int]:
    model = (requested or "").strip() or await default_embedding_model(data_residency=org.data_residency)
    if org.data_residency == "eu_strict" and model.startswith(VOYAGE_PREFIX):
        raise KnowledgeError(
            "Tu organización exige residencia UE estricta: usa embeddings locales o de Bedrock UE",
            code="eu_strict_embeddings",
        )
    dim = model_dim(model)
    if model == LOCAL_DEFAULT_MODEL and not await local_model_available(model):
        raise EmbeddingUnavailable("El modelo local de embeddings no está disponible en este momento")
    if not 8 <= dim <= 2000:
        raise KnowledgeError("La dimensión del modelo no es compatible con el índice vectorial", code="embedding_dim")
    return model, dim


async def create_kb(
    principal: Principal,
    *,
    name: str,
    description: str = "",
    embedding_model: str | None = None,
    project_id: uuid.UUID | None = None,
    chunk_size_tokens: int = 800,
    chunk_overlap_tokens: int = 120,
) -> KnowledgeBase:
    """Create a knowledge base and its database objects in one owner transaction (role checked by caller)."""
    if principal.org_id is None:
        raise KnowledgeError("Selecciona una organización", code="no_active_org")
    name = name.strip()
    if not name:
        raise KnowledgeError("El nombre es obligatorio", code="invalid_name")
    if chunk_overlap_tokens >= chunk_size_tokens:
        raise KnowledgeError("El solapamiento debe ser menor que el tamaño del fragmento", code="invalid_chunking")
    async with system_session() as s:
        org = await s.get(Org, principal.org_id)
        if org is None:
            raise KnowledgeError("Organización no encontrada", status=404)
        if project_id is not None:
            project = await s.get(Project, project_id)
            if project is None or project.org_id != org.id:
                raise KnowledgeError("Proyecto no encontrado", code="project_not_found", status=404)
        model, dim = await resolve_embedding_model(org, embedding_model)
        schema_name, reader_role = new_kb_identifiers()
        kb = KnowledgeBase(
            org_id=org.id,
            project_id=project_id,
            name=name[:200],
            description=description.strip(),
            embedding_model=model,
            embedding_dim=dim,
            governance_mode="off",
            schema_name=schema_name,
            reader_role=reader_role,
            chunk_size_tokens=chunk_size_tokens,
            chunk_overlap_tokens=chunk_overlap_tokens,
            created_by=principal.user_id,
        )
        s.add(kb)
        await s.flush()
        await provision(s, kb)
        await record_audit(
            s,
            action="knowledge.kb.create",
            principal=principal,
            entity_type="knowledge_base",
            entity_id=kb.id,
            diff={"name": kb.name, "embedding_model": model, "project_id": project_id},
        )
        await s.flush()
        await s.refresh(kb)
        s.expunge(kb)
    await ensure_vector_index(kb)
    return kb


async def update_kb(
    session: AsyncSession, principal: Principal, kb: KnowledgeBase, changes: dict[str, Any]
) -> KnowledgeBase:
    """Apply validated changes (RLS session; governance_mode requires admin, checked by the caller)."""
    before: dict[str, Any] = {}
    if "name" in changes and changes["name"] is not None:
        value = str(changes["name"]).strip()
        if not value:
            raise KnowledgeError("El nombre es obligatorio", code="invalid_name")
        before["name"], kb.name = kb.name, value[:200]
    if "description" in changes and changes["description"] is not None:
        before["description"], kb.description = kb.description, str(changes["description"]).strip()
    if "governance_mode" in changes and changes["governance_mode"] is not None:
        mode = str(changes["governance_mode"])
        if mode not in GOVERNANCE_MODES:
            raise KnowledgeError("Modo de gobierno no válido", code="invalid_governance_mode")
        before["governance_mode"], kb.governance_mode = kb.governance_mode, mode
    size = changes.get("chunk_size_tokens")
    overlap = changes.get("chunk_overlap_tokens")
    if size is not None or overlap is not None:
        new_size = int(size if size is not None else kb.chunk_size_tokens)
        new_overlap = int(overlap if overlap is not None else kb.chunk_overlap_tokens)
        if not (100 <= new_size <= 4000) or not (0 <= new_overlap < new_size):
            raise KnowledgeError("Tamaño o solapamiento de fragmento no válidos", code="invalid_chunking")
        before["chunk_size_tokens"], kb.chunk_size_tokens = kb.chunk_size_tokens, new_size
        before["chunk_overlap_tokens"], kb.chunk_overlap_tokens = kb.chunk_overlap_tokens, new_overlap
    if before:
        await record_audit(
            session,
            action="knowledge.kb.update",
            principal=principal,
            entity_type="knowledge_base",
            entity_id=kb.id,
            diff={"before": before, "after": {k: getattr(kb, k) for k in before}},
        )
    await session.flush()
    return kb


async def delete_kb(principal: Principal, kb_id: uuid.UUID) -> None:
    """Delete the knowledge base, its schema, reader role, files and backups (role checked by caller)."""
    async with system_session() as s:
        kb = await s.get(KnowledgeBase, kb_id)
        if kb is None or kb.org_id != principal.org_id:
            raise KnowledgeError("Base de conocimiento no encontrada", status=404)
        paths = [p for (p,) in await s.execute(select(KbFile.path).where(KbFile.kb_id == kb.id))]
        paths += [p for (p,) in await s.execute(select(KbBackup.path).where(KbBackup.kb_id == kb.id)) if p]
        schema_name, name = kb.schema_name, kb.name
        await deprovision(s, kb)
        await s.delete(kb)
        await record_audit(
            s,
            action="knowledge.kb.delete",
            principal=principal,
            entity_type="knowledge_base",
            entity_id=kb_id,
            diff={"name": name, "files": len(paths)},
        )
    await drop_vector_index(schema_name)
    await delete_blobs(paths)
    await publish_kb_event(kb_id, {"type": "kb_deleted", "kb_id": str(kb_id)})


async def kb_stats(session: AsyncSession, kb_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
    """Counts per knowledge base: files by status, total size, chunks, tables."""
    stats: dict[uuid.UUID, dict[str, Any]] = {
        k: {"files": 0, "files_ready": 0, "files_processing": 0, "files_error": 0, "size": 0, "chunks": 0, "tables": 0}
        for k in kb_ids
    }
    if not kb_ids:
        return stats
    rows = await session.execute(
        select(KbFile.kb_id, KbFile.status, func.count(), func.coalesce(func.sum(KbFile.size), 0))
        .where(KbFile.kb_id.in_(kb_ids))
        .group_by(KbFile.kb_id, KbFile.status)
    )
    for kb_id, status, count, size in rows:
        entry = stats[kb_id]
        entry["files"] += int(count)
        entry["size"] += int(size)
        if status == "ready":
            entry["files_ready"] += int(count)
        elif status == "error":
            entry["files_error"] += int(count)
        else:
            entry["files_processing"] += int(count)
    for kb_id, count in await session.execute(
        select(KbChunk.kb_id, func.count()).where(KbChunk.kb_id.in_(kb_ids)).group_by(KbChunk.kb_id)
    ):
        stats[kb_id]["chunks"] = int(count)
    for kb_id, count in await session.execute(
        select(KbTable.kb_id, func.count()).where(KbTable.kb_id.in_(kb_ids)).group_by(KbTable.kb_id)
    ):
        stats[kb_id]["tables"] = int(count)
    return stats
