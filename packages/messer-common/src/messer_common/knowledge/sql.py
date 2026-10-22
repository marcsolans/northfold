"""Read-only SQL executor for the console and for agents.

Every statement runs on the ``messer_readonly`` connection inside a READ ONLY transaction that:

1. sets ``statement_timeout`` and ``lock_timeout``;
2. sets ``app.kb_scope`` to the knowledge base (the only one ``kb_*_search`` will accept);
3. sets ``search_path`` to the knowledge base schema, then ``public``;
4. switches to the knowledge base reader role (``kb_<hex>_reader``), which can only read that schema.

The statement is checked first (:mod:`.sqlcheck`), ``embed('…')`` calls become a computed vector
parameter (``$n::vector``), policies for the caller's role are applied (row filters and masks become
CTEs that shadow the protected tables), and results are fetched through a server-side cursor so at most
``limit + 1`` rows ever leave the database.
"""

from __future__ import annotations

import asyncio
import base64
import math
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from datetime import time as dtime
from decimal import Decimal
from typing import Any, LiteralString, cast

import psycopg
from psycopg import errors as pg_errors
from sqlalchemy import text

from ..db.models import KnowledgeBase
from ..db.session import get_readonly_engine, system_session
from ..logging import get_logger
from ..settings import get_settings
from . import policies as pol
from .embeddings import get_embedder, to_pgvector
from .errors import KbNotFound, SqlExecutionError, SqlRejected, SqlTimeout
from .sqlcheck import SEARCH_FUNCTIONS, analyze, params_in, quote_ident, replace_spans

log = get_logger("messer.knowledge.sql")

MAX_ROW_LIMIT = 10_000
_CURSOR = "messer_console"
_semaphore: asyncio.Semaphore | None = None


def _gate() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(8)
    return _semaphore


@dataclass(slots=True)
class KbMeta:
    id: uuid.UUID
    org_id: uuid.UUID
    schema_name: str
    reader_role: str
    embedding_model: str
    embedding_dim: int
    governance_mode: str


@dataclass(slots=True)
class SqlResult:
    columns: list[str]
    column_types: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    elapsed_ms: float
    plan: Any | None = None
    policy: dict[str, Any] | None = None
    notices: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "columns": self.columns,
            "column_types": self.column_types,
            "rows": self.rows,
            "row_count": self.row_count,
            "truncated": self.truncated,
            "elapsed_ms": self.elapsed_ms,
        }
        if self.plan is not None:
            data["plan"] = self.plan
        if self.policy is not None:
            data["policy"] = self.policy
        if self.notices:
            data["notices"] = self.notices
        return data

    def __getitem__(self, key: str) -> Any:
        """Dict-style access (``result["rows"]``) as described in the contract."""
        return getattr(self, key)


async def load_kb_meta(kb_id: uuid.UUID) -> KbMeta:
    async with system_session() as s:
        kb = await s.get(KnowledgeBase, kb_id)
        if kb is None:
            raise KbNotFound("Base de conocimiento no encontrada")
        return KbMeta(
            id=kb.id,
            org_id=kb.org_id,
            schema_name=kb.schema_name,
            reader_role=kb.reader_role,
            embedding_model=kb.embedding_model,
            embedding_dim=kb.embedding_dim,
            governance_mode=kb.governance_mode,
        )


async def relation_columns(schema: str) -> dict[str, list[str]]:
    """Columns of every table and view in a knowledge base schema (owner connection)."""
    async with system_session() as s:
        rows = await s.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = :schema ORDER BY table_name, ordinal_position"
            ),
            {"schema": schema},
        )
        out: dict[str, list[str]] = {}
        for table_name, column_name in rows:
            out.setdefault(str(table_name), []).append(str(column_name))
        return out


def _trusted(statement: str) -> LiteralString:
    """Mark a statement as vetted: built from quoted identifiers or checked by :mod:`.sqlcheck`."""
    return cast(LiteralString, statement)


def jsonable(value: Any) -> Any:
    """Database value → JSON-safe value."""
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            return str(value)
        if value == value.to_integral_value() and abs(value) < 2**53:
            return int(value)
        as_float = float(value)
        return as_float if abs(value) < Decimal(10) ** 15 else str(value)
    if isinstance(value, datetime | date | dtime):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, bytes | bytearray | memoryview):
        raw = bytes(value)
        return {"base64": base64.b64encode(raw[:4096]).decode(), "truncated": len(raw) > 4096}
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    return str(value)


def _json_param(value: Any) -> Any:
    if isinstance(value, dict):
        from psycopg.types.json import Jsonb

        return Jsonb(value)
    return value


def _map_error(exc: psycopg.Error, timeout_ms: int) -> Exception:
    diag = exc.diag
    message = (diag.message_primary or str(exc)).strip()
    details: dict[str, Any] = {"sqlstate": exc.sqlstate}
    if diag.message_detail:
        details["detail"] = diag.message_detail
    if diag.message_hint:
        details["hint"] = diag.message_hint
    if diag.statement_position:
        details["position"] = int(diag.statement_position)
    if isinstance(exc, pg_errors.QueryCanceled):
        return SqlTimeout(f"La consulta superó el tiempo máximo de {timeout_ms} ms", details=details)
    if isinstance(exc, pg_errors.InsufficientPrivilege):
        return SqlRejected(f"Permiso denegado: {message}", code="sql_permission", details=details)
    if isinstance(exc, pg_errors.ReadOnlySqlTransaction):
        return SqlRejected("La consola es de solo lectura", code="sql_not_read_only", details=details)
    return SqlExecutionError(message, details=details)


async def _type_names(pg: psycopg.AsyncConnection[Any], oids: list[int]) -> dict[int, str]:
    names: dict[int, str] = {}
    missing: list[int] = []
    for oid in oids:
        info = pg.adapters.types.get(oid)
        if info is not None:
            names[oid] = info.name
        else:
            missing.append(oid)
    if missing:
        async with pg.cursor() as cur:
            await cur.execute("SELECT oid::int, typname FROM pg_catalog.pg_type WHERE oid = ANY(%s)", [missing])
            for oid, name in await cur.fetchall():
                names[int(oid)] = str(name)
    return names


@dataclass(slots=True)
class PreparedStatement:
    sql: str
    params: list[Any]
    is_explain: bool
    policy: pol.PolicyReport | None


async def prepare(
    kb: KbMeta,
    sql: str,
    params: list[Any] | None,
    *,
    role: str | None,
    break_glass: bool,
    apply_policies: bool = True,
) -> PreparedStatement:
    """Validate, expand ``embed()``, apply policies. Raises SqlRejected."""
    params = list(params or [])
    analysis = analyze(sql, own_schema=kb.schema_name)
    if analysis.max_param != len(params):
        if analysis.max_param > len(params):
            raise SqlRejected(
                f"La consulta usa ${analysis.max_param} pero solo se han enviado {len(params)} parámetros",
                code="sql_params",
            )
        raise SqlRejected(
            f"Se han enviado {len(params)} parámetros pero la consulta solo usa {analysis.max_param}",
            code="sql_params",
        )
    missing = set(range(1, analysis.max_param + 1)) - analysis.params_used
    if missing:
        raise SqlRejected(f"Falta el parámetro ${min(missing)} en la consulta", code="sql_params")

    statement = analysis.sql
    replacements: list[tuple[int, int, str]] = []
    final_params = [_json_param(p) for p in params]
    if analysis.embed_calls:
        embedder = get_embedder(kb.embedding_model)
        for call in analysis.embed_calls:
            if call.param is not None:
                value = params[call.param - 1]
                if not isinstance(value, str) or not value.strip():
                    raise SqlRejected(f"embed(${call.param}) necesita un texto", code="sql_embed")
                source = value
            else:
                source = call.text or ""
            vector = await embedder.embed_query(source)
            final_params.append(to_pgvector(vector))
            replacements.append((call.start, call.end, f"${len(final_params)}::vector({kb.embedding_dim})"))

    report: pol.PolicyReport | None = None
    ctes: list[str] = []
    if apply_policies and kb.governance_mode in ("shadow", "enforce"):
        async with system_session() as s:
            rules = await pol.load_rules(s, kb.id, role)
        effective = pol.combine(rules, break_glass=break_glass)
        report = pol.PolicyReport(mode=kb.governance_mode, role=pol.policy_role(role), break_glass=break_glass)
        protected = pol.relation_policies(effective)
        referenced = {name for name in protected if name in analysis.names} | {
            name for schema, name in analysis.qualified if schema == kb.schema_name and name in protected
        }
        if referenced:
            columns = await relation_columns(kb.schema_name)
            for relation in sorted(referenced):
                eff = protected[relation]
                entry = {"relation": relation, **eff.describe()}
                if kb.governance_mode == "shadow":
                    report.would_apply.append(entry)
                    continue
                if (kb.schema_name, relation) in analysis.qualified:
                    raise SqlRejected(
                        f"La tabla {relation} tiene políticas: consúltala sin el prefijo de esquema",
                        code="sql_policy",
                    )
                if relation in columns:
                    ctes.append(pol.cte_sql(kb.schema_name, relation, columns[relation], eff))
                    report.applied.append(entry)
        documents_policy = effective.get(pol.DOCUMENTS_TABLE)
        if documents_policy is not None and analysis.functions & SEARCH_FUNCTIONS:
            entry = {"relation": "kb_*_search", **documents_policy.describe()}
            if kb.governance_mode == "enforce":
                raise SqlRejected(
                    "Hay políticas sobre los documentos para tu rol: usa la vista chunks en lugar de kb_*_search",
                    code="sql_policy",
                )
            report.would_apply.append(entry)
        if report.would_apply:
            log.info(
                "knowledge.policy.shadow",
                kb_id=str(kb.id),
                role=report.role,
                would_apply=[w["relation"] for w in report.would_apply],
            )

    if replacements:
        statement = replace_spans(statement, replacements)
    # Parameters no longer referenced (only used inside embed()) still need a type for PostgreSQL.
    unused = [n for n in range(1, len(params) + 1) if n not in params_in(statement)]
    if unused:
        ctes.append(
            quote_ident("_messer_params") + " AS (SELECT " + ", ".join(f"${n}::text AS p{n}" for n in unused) + ")"
        )
    if ctes:
        statement = _inject_ctes(statement, ctes, replacements, analysis.statement_offset, analysis.with_insert_offset)
    return PreparedStatement(sql=statement, params=final_params, is_explain=analysis.is_explain, policy=report)


def _shift(offset: int, replacements: list[tuple[int, int, str]]) -> int:
    """Offset in the rewritten statement for an offset of the original one."""
    delta = 0
    for start, end, new in replacements:
        if end <= offset:
            delta += len(new) - (end - start)
    return offset + delta


def _inject_ctes(
    statement: str,
    ctes: list[str],
    replacements: list[tuple[int, int, str]],
    statement_offset: int,
    with_insert_offset: int | None,
) -> str:
    joined = ", ".join(ctes)
    if with_insert_offset is not None:
        at = _shift(with_insert_offset, replacements)
        return statement[:at] + " " + joined + "," + statement[at:]
    at = _shift(statement_offset, replacements)
    return statement[:at] + "WITH " + joined + " " + statement[at:]


async def run_readonly(
    *,
    kb_id: uuid.UUID,
    sql: str,
    params: list[Any] | None = None,
    limit: int | None = None,
    explain: bool = False,
    role: str | None = None,
    break_glass: bool = False,
    timeout_ms: int | None = None,
    apply_policies: bool = True,
) -> SqlResult:
    """Run one read-only statement against a knowledge base (see module docstring).

    ``role`` selects the policies to apply (organization role; None = agents/API keys).
    ``apply_policies=False`` is for internal callers that already applied them (search).
    """
    settings = get_settings()
    row_limit = max(1, min(limit or settings.sql_row_limit, MAX_ROW_LIMIT))
    timeout = max(100, timeout_ms or settings.sql_statement_timeout_ms)
    kb = await load_kb_meta(kb_id)
    prepared = await prepare(kb, sql, params, role=role, break_glass=break_glass, apply_policies=apply_policies)
    started = time.perf_counter()
    async with _gate():
        try:
            async with asyncio.timeout(timeout / 1000 + 10):
                result = await _execute(kb, prepared, row_limit=row_limit, timeout_ms=timeout, explain=explain)
        except TimeoutError as exc:
            raise SqlTimeout(f"La consulta superó el tiempo máximo de {timeout} ms") from exc
    result.elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    result.policy = prepared.policy.to_dict() if prepared.policy is not None else None
    return result


async def _execute(
    kb: KbMeta, prepared: PreparedStatement, *, row_limit: int, timeout_ms: int, explain: bool
) -> SqlResult:
    engine = get_readonly_engine()
    async with engine.connect() as conn:
        raw = await conn.get_raw_connection()
        pg: psycopg.AsyncConnection[Any] = raw.driver_connection  # type: ignore[assignment]
        try:
            async with pg.cursor() as cur:
                await cur.execute("SET TRANSACTION READ ONLY")
                await cur.execute(_trusted(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))
                await cur.execute(_trusted(f"SET LOCAL lock_timeout = {min(int(timeout_ms), 2000)}"))
                await cur.execute("SET LOCAL idle_in_transaction_session_timeout = 60000")
                await cur.execute("SELECT set_config('app.kb_scope', %s, true)", [str(kb.id)])
                await cur.execute(_trusted(f"SET LOCAL search_path = {quote_ident(kb.schema_name)}, public"))
                await cur.execute(_trusted(f"SET LOCAL ROLE {quote_ident(kb.reader_role)}"))
            raw_cursor = psycopg.AsyncRawCursor(pg)
            try:
                if explain:
                    await raw_cursor.execute(_trusted("EXPLAIN (FORMAT JSON) " + prepared.sql), prepared.params)
                    row = await raw_cursor.fetchone()
                    plan = row[0] if row else None
                    return SqlResult([], [], [], 0, False, 0.0, plan=plan)
                if prepared.is_explain:
                    await raw_cursor.execute(_trusted(prepared.sql), prepared.params)
                    fetched = await raw_cursor.fetchmany(row_limit + 1)
                    description = raw_cursor.description or []
                else:
                    await raw_cursor.execute(
                        _trusted(f"DECLARE {_CURSOR} NO SCROLL CURSOR FOR {prepared.sql}"), prepared.params
                    )
                    await raw_cursor.execute(_trusted(f"FETCH FORWARD {row_limit + 1} FROM {_CURSOR}"))
                    fetched = await raw_cursor.fetchall()
                    description = raw_cursor.description or []
            finally:
                await raw_cursor.close()
            truncated = len(fetched) > row_limit
            rows = [[jsonable(v) for v in r] for r in fetched[:row_limit]]
            oids = [int(d.type_code) for d in description]
            names = await _type_names(pg, sorted(set(oids)))
            return SqlResult(
                columns=[d.name for d in description],
                column_types=[names.get(o, str(o)) for o in oids],
                rows=rows,
                row_count=len(rows),
                truncated=truncated,
                elapsed_ms=0.0,
            )
        except psycopg.Error as exc:
            raise _map_error(exc, timeout_ms) from exc
        finally:
            try:
                await pg.rollback()
            except psycopg.Error:
                await conn.invalidate()
