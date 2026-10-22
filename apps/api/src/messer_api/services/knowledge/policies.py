"""Validation of knowledge base policies before they are stored."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db.models import KbTable, KnowledgeBase
from messer_common.knowledge import policies as pol
from messer_common.knowledge.errors import KnowledgeError, PolicyError
from messer_common.knowledge.sql import run_readonly
from messer_common.knowledge.sqlcheck import quote_ident, validate_expression

from .tables import column_types

DOCUMENT_COLUMNS = ("content", "heading", "filename", "metadata")


async def policy_columns(session: AsyncSession, kb: KnowledgeBase, table: str) -> list[str]:
    if table == pol.DOCUMENTS_TABLE:
        return list(DOCUMENT_COLUMNS)
    row = (
        await session.execute(select(KbTable).where(KbTable.kb_id == kb.id, KbTable.name == table))
    ).scalar_one_or_none()
    if row is None:
        raise PolicyError(f"La tabla {table} no existe en esta base de conocimiento", code="policy_table")
    return list(column_types(row))


async def validate_policy(
    session: AsyncSession,
    kb: KnowledgeBase,
    *,
    table: str,
    role: str,
    row_filter_sql: str | None,
    masked_columns: dict[str, Any],
) -> tuple[str | None, dict[str, str]]:
    """Normalized (row filter, masks). Raises PolicyError with a user-facing message."""
    if role not in pol.POLICY_ROLES:
        raise PolicyError(f"Rol no válido: {role}", code="policy_role")
    columns = await policy_columns(session, kb, table)
    masks: dict[str, str] = {}
    for column, mode in (masked_columns or {}).items():
        name = str(column)
        allowed = name in columns or (table == pol.DOCUMENTS_TABLE and name.startswith("metadata.") and len(name) > 9)
        if not allowed:
            raise PolicyError(f"La columna {name} no existe", code="policy_column", details={"column": name})
        kind, n = pol.parse_mask(str(mode))
        masks[name] = f"truncate:{n}" if kind == "truncate" else kind
    row_filter = (row_filter_sql or "").strip() or None
    if row_filter:
        try:
            validate_expression(row_filter)
        except KnowledgeError as exc:
            raise PolicyError(exc.message, code="policy_filter") from exc
        relations = ["documents", "chunks"] if table == pol.DOCUMENTS_TABLE else [table]
        for relation in relations:
            try:
                await run_readonly(
                    kb_id=kb.id,
                    sql=f"SELECT 1 FROM {quote_ident(relation)} WHERE ({row_filter}) LIMIT 1",
                    limit=1,
                    apply_policies=False,
                )
            except KnowledgeError as exc:
                hint = (
                    " Los filtros de documentos solo pueden usar filename y metadata." if relations != [table] else ""
                )
                raise PolicyError(
                    f"El filtro de filas no es válido: {exc.message}.{hint}", code="policy_filter", details=exc.details
                ) from exc
        if table == pol.DOCUMENTS_TABLE:
            try:
                await run_readonly(
                    kb_id=kb.id,
                    sql=f"SELECT 1 FROM kb_text_search($1::uuid, 'x', 1) AS h WHERE ({row_filter}) LIMIT 1",
                    params=[str(kb.id)],
                    limit=1,
                    apply_policies=False,
                )
            except KnowledgeError as exc:
                raise PolicyError(
                    "El filtro de documentos solo puede usar filename y metadata", code="policy_filter"
                ) from exc
    if not row_filter and not masks:
        raise PolicyError("Define un filtro de filas o al menos una columna enmascarada", code="policy_empty")
    return row_filter, masks
