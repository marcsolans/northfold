"""Knowledge search: vector, keyword (Spanish + English full text) and hybrid (Reciprocal Rank Fusion).

``search(session, kb_id=…, query=…)`` runs the ``kb_*_search`` SQL functions on the caller's session. With
an RLS session the knowledge base must belong to the active organization; with a system session the caller
is trusted (data plane) and must have checked the organization itself.

Policies on ``*documents*`` for the caller's role are honored: masks apply to the returned fields, and row
filters are evaluated on the hit columns (``filename``, ``heading``, ``content``, ``metadata``,
``page_from``, ``page_to``, ``file_id``) through the read-only executor under the knowledge base reader role.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import KnowledgeBase
from ..logging import get_logger
from . import policies as pol
from .embeddings import get_embedder, to_pgvector
from .errors import KbNotFound, KnowledgeError
from .sql import run_readonly

log = get_logger("messer.knowledge.search")

SearchMode = Literal["vector", "keyword", "hybrid"]
MAX_K = 50


@dataclass(slots=True)
class SearchHit:
    chunk_id: str
    file_id: str
    filename: str
    content: str
    heading: str | None
    page_from: int | None
    page_to: int | None
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def __getitem__(self, key: str) -> Any:
        """Dict-style access (``hit["content"]``) as described in the contract."""
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


def _hit(row: Any) -> SearchHit:
    data = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
    return SearchHit(
        chunk_id=str(data["chunk_id"]),
        file_id=str(data["file_id"]),
        filename=str(data["filename"]),
        content=str(data["content"]),
        heading=data.get("heading"),
        page_from=data.get("page_from"),
        page_to=data.get("page_to"),
        score=float(data.get("score") or 0.0),
        metadata=dict(data.get("metadata") or {}),
    )


def _function_sql(mode: SearchMode, dim: int, placeholders: tuple[str, str, str, str]) -> str:
    kb, query, embedding, k = placeholders
    if mode == "vector":
        return f"SELECT * FROM kb_vector_search({kb}, CAST({embedding} AS vector({dim})), {k})"
    if mode == "keyword":
        return f"SELECT * FROM kb_text_search({kb}, {query}, {k})"
    return f"SELECT * FROM kb_hybrid_search({kb}, {query}, CAST({embedding} AS vector({dim})), {k})"


async def search(
    session: AsyncSession,
    *,
    kb_id: uuid.UUID,
    query: str,
    mode: SearchMode = "hybrid",
    k: int = 8,
    role: str | None = None,
    break_glass: bool = False,
) -> list[SearchHit]:
    """Top ``k`` chunks for ``query``. ``role`` selects the policies to apply (None = agent)."""
    if mode not in ("vector", "keyword", "hybrid"):
        raise KnowledgeError("Modo de búsqueda no válido", code="invalid_mode")
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None:
        raise KbNotFound("Base de conocimiento no encontrada")
    query = query.strip()
    if not query:
        return []
    k = max(1, min(int(k), MAX_K))
    started = time.perf_counter()
    embedding: str | None = None
    if mode in ("vector", "hybrid"):
        embedding = to_pgvector(await get_embedder(kb.embedding_model).embed_query(query))

    documents_policy: pol.EffectivePolicy | None = None
    if kb.governance_mode == "enforce":
        rules = [r for r in await pol.load_rules(session, kb.id, role) if r.table == pol.DOCUMENTS_TABLE]
        documents_policy = pol.combine(rules, break_glass=break_glass).get(pol.DOCUMENTS_TABLE)

    if documents_policy is not None and documents_policy.row_filters:
        hits = await _filtered_search(kb, mode, query, embedding, k, documents_policy)
    else:
        await session.execute(text("SELECT set_config('app.kb_scope', :kb, true)"), {"kb": str(kb.id)})
        try:
            rows = await session.execute(
                text(_function_sql(mode, kb.embedding_dim, (":kb", ":q", ":emb", ":k"))),
                {"kb": kb.id, "q": query, "emb": embedding, "k": k},
            )
            hits = [_hit(r) for r in rows]
        finally:
            await session.execute(text("SELECT set_config('app.kb_scope', '', true)"))
    if documents_policy is not None and documents_policy.masks:
        hits = [SearchHit(**pol.mask_hit_fields(h.to_dict(), documents_policy)) for h in hits]
    log.info(
        "knowledge.search",
        kb_id=str(kb.id),
        mode=mode,
        k=k,
        hits=len(hits),
        ms=round((time.perf_counter() - started) * 1000, 1),
    )
    return hits


async def _filtered_search(
    kb: KnowledgeBase,
    mode: SearchMode,
    query: str,
    embedding: str | None,
    k: int,
    eff: pol.EffectivePolicy,
) -> list[SearchHit]:
    """Search with document row filters, evaluated by the read-only executor (reader role)."""
    pool = min(k * 4, 200)
    dim = kb.embedding_dim
    params: list[Any]
    if mode == "vector":
        inner = f"SELECT * FROM kb_vector_search($1::uuid, $2::vector({dim}), $3)"
        params = [str(kb.id), embedding, pool]
    elif mode == "keyword":
        inner = "SELECT * FROM kb_text_search($1::uuid, $2, $3)"
        params = [str(kb.id), query, pool]
    else:
        inner = f"SELECT * FROM kb_hybrid_search($1::uuid, $2, $3::vector({dim}), $4)"
        params = [str(kb.id), query, embedding, pool]
    where = " AND ".join(f"({f})" for f in eff.row_filters)
    sql = f"SELECT h.* FROM ({inner}) AS h WHERE {where} ORDER BY h.score DESC LIMIT {int(k)}"
    result = await run_readonly(kb_id=kb.id, sql=sql, params=params, limit=k, apply_policies=False)
    return [_hit(dict(zip(result.columns, row, strict=True))) for row in result.rows]
