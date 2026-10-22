"""Structured data in knowledge bases: tables in the ``kb_<hex>`` schema.

Writes (create, evolve, load, edit) run on the owner connection; reads for people and agents go through
the read-only executor so per-role policies apply. Uploaded CSV/Excel tables get a ``_row_id`` identity
primary key; synced tables use the source primary key and merge on it.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from psycopg.types.json import Jsonb
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db.models import KbFile, KbTable, KnowledgeBase
from messer_common.knowledge import coltypes as ct
from messer_common.knowledge.errors import KbNotFound, KnowledgeError
from messer_common.knowledge.parsing import ParsedTable
from messer_common.knowledge.sql import SqlResult, jsonable, run_readonly
from messer_common.knowledge.sqlcheck import quote_ident, quote_literal

FilterOp = Literal["eq", "neq", "lt", "lte", "gt", "gte", "contains", "starts", "is_null", "not_null"]
_FILTER_SQL: dict[str, str] = {"eq": "=", "neq": "<>", "lt": "<", "lte": "<=", "gt": ">", "gte": ">="}
MAX_INVALID_EXAMPLES = 5
_COPY_TYPES = {"bigint": "int8", "boolean": "bool"}


@dataclass(slots=True)
class LoadStats:
    rows: int = 0
    skipped_rows: int = 0
    invalid_values: int = 0
    examples: list[str] | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "skipped_rows": self.skipped_rows,
            "invalid_values": self.invalid_values,
            "examples": list(self.examples or []),
        }


def _q(schema: str, name: str) -> str:
    return f"{quote_ident(schema)}.{quote_ident(name)}"


def table_columns(table: KbTable) -> list[dict[str, Any]]:
    return list((table.schema_json or {}).get("columns", []))


def table_primary_key(table: KbTable) -> list[str]:
    pk = list((table.schema_json or {}).get("primary_key", []))
    return pk or [ct.ROW_ID]


def column_types(table: KbTable) -> dict[str, str]:
    types = {c["name"]: c["type"] for c in table_columns(table)}
    if not (table.schema_json or {}).get("primary_key"):
        types[ct.ROW_ID] = "integer"
    return types


async def _lock(session: AsyncSession, kb_id: uuid.UUID, name: str) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"kb-table:{kb_id}:{name}"}
    )


async def _existing_columns(session: AsyncSession, schema: str, name: str) -> dict[str, str]:
    rows = await session.execute(
        text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = :s AND table_name = :t ORDER BY ordinal_position"
        ),
        {"s": schema, "t": name},
    )
    return {str(c): str(t) for c, t in rows}


async def _create_table(
    session: AsyncSession, kb: KnowledgeBase, name: str, columns: list[ct.ColumnSpec], primary_key: list[str]
) -> None:
    parts: list[str] = []
    if not primary_key:
        parts.append(f"{quote_ident(ct.ROW_ID)} bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY")
    for col in columns:
        null = " NOT NULL" if (col.name in primary_key or not col.nullable) else ""
        parts.append(f"{quote_ident(col.name)} {ct.PG_TYPES[col.type]}{null}")
    if primary_key:
        parts.append("PRIMARY KEY (" + ", ".join(quote_ident(c) for c in primary_key) + ")")
    target = _q(kb.schema_name, name)
    await session.execute(text(f"CREATE TABLE {target} (" + ", ".join(parts) + ")"))
    for col in columns:
        if col.comment:
            await session.execute(
                text(f"COMMENT ON COLUMN {target}.{quote_ident(col.name)} IS {quote_literal(col.comment[:1000])}")
            )
    await session.execute(text(f"GRANT SELECT ON {target} TO {quote_ident(kb.reader_role)}"))


def _coerce_row(
    values: list[Any], types: list[str], stats: LoadStats, pk_index: set[int], names: list[str]
) -> list[Any] | None:
    out: list[Any] = []
    for i, (value, logical) in enumerate(zip(values, types, strict=True)):
        try:
            coerced = ct.coerce(value, logical)
        except ct.CoercionError as exc:
            stats.invalid_values += 1
            if stats.examples is not None and len(stats.examples) < MAX_INVALID_EXAMPLES:
                stats.examples.append(f"{names[i]}: {exc}")
            coerced = None
        if coerced is None and i in pk_index:
            stats.skipped_rows += 1
            return None
        out.append(Jsonb(coerced) if logical == "json" and coerced is not None else coerced)
    return out


async def _load_rows(
    session: AsyncSession,
    kb: KnowledgeBase,
    name: str,
    names: list[str],
    types: list[str],
    rows: list[list[Any]],
    primary_key: list[str],
) -> LoadStats:
    """Bulk load through COPY into a temporary staging table, then INSERT (merge on the primary key)."""
    stats = LoadStats(examples=[])
    pk_index = {names.index(c) for c in primary_key}
    prepared: list[list[Any]] = []
    seen: dict[tuple[Any, ...], int] = {}
    for raw in rows:
        values = list(raw) + [None] * (len(names) - len(raw))
        row = _coerce_row(values[: len(names)], types, stats, pk_index, names)
        if row is None:
            continue
        if primary_key:
            key = tuple(str(row[i]) for i in sorted(pk_index))
            if key in seen:  # last value wins within one load
                prepared[seen[key]] = row
                continue
            seen[key] = len(prepared)
        prepared.append(row)
    stats.rows = len(prepared)
    if not prepared:
        return stats

    conn = await session.connection()
    raw_conn = await conn.get_raw_connection()
    pg: Any = raw_conn.driver_connection
    pg_types = [ct.PG_TYPES[t] for t in types]
    stage = quote_ident("_messer_stage")
    cols = ", ".join(quote_ident(n) for n in names)
    target = _q(kb.schema_name, name)
    async with pg.cursor() as cur:
        await cur.execute(f"DROP TABLE IF EXISTS pg_temp.{stage}")
        await cur.execute(
            f"CREATE TEMP TABLE {stage} ("
            + ", ".join(f"{quote_ident(n)} {t}" for n, t in zip(names, pg_types, strict=True))
            + ") ON COMMIT DROP"
        )
        async with cur.copy(f"COPY pg_temp.{stage} ({cols}) FROM STDIN") as copy:
            copy.set_types([_COPY_TYPES.get(t, t) for t in pg_types])
            for row in prepared:
                await copy.write_row(row)
        if primary_key:
            updates = [n for n in names if n not in primary_key]
            conflict = ", ".join(quote_ident(c) for c in primary_key)
            action = (
                "DO UPDATE SET " + ", ".join(f"{quote_ident(n)} = EXCLUDED.{quote_ident(n)}" for n in updates)
                if updates
                else "DO NOTHING"
            )
            await cur.execute(
                f"INSERT INTO {target} ({cols}) SELECT {cols} FROM pg_temp.{stage} ON CONFLICT ({conflict}) {action}"
            )
        else:
            await cur.execute(f"INSERT INTO {target} ({cols}) SELECT {cols} FROM pg_temp.{stage}")
        await cur.execute(f"DROP TABLE pg_temp.{stage}")
    return stats


async def _row_count(session: AsyncSession, kb: KnowledgeBase, name: str) -> int:
    return int((await session.execute(text(f"SELECT count(*) FROM {_q(kb.schema_name, name)}"))).scalar_one())


def _table_name(raw: str) -> str:
    name = ct.sanitize_identifier(raw, fallback="tabla")
    if name in ct.RESERVED_TABLES or name.startswith("pg_") or name.startswith("_"):
        name = f"{name.strip('_')}_data"
    return name[:63]


def _spec_from_dict(col: dict[str, Any]) -> ct.ColumnSpec:
    if "name" not in col:
        raise KnowledgeError("Cada columna necesita un nombre", code="invalid_columns")
    try:
        logical = ct.logical_type(str(col.get("type", "text")))
    except ct.CoercionError as exc:
        raise KnowledgeError(str(exc), code="invalid_column_type", details={"column": col.get("name")}) from exc
    return ct.ColumnSpec(
        name=str(col["name"]),
        type=logical,
        nullable=bool(col.get("nullable", True)),
        comment=(str(col["comment"]) if col.get("comment") else None),
        source_name=str(col["name"]),
    )


async def upsert_table(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    kb_id: uuid.UUID,
    table: str,
    columns: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    primary_key: list[str],
    source: str = "sync",
    sync_id: uuid.UUID | None = None,
    description: str | None = None,
    replace: bool = False,
) -> KbTable:
    """Create or evolve ``table`` in the knowledge base schema and merge ``rows`` on ``primary_key``.

    ``session`` must be an owner (system) session. ``columns``: ``{"name", "type", "nullable", "comment"}``
    with type ``text|integer|numeric|boolean|date|timestamp|json``. New columns are added; a changed type is
    converted when every value converts, otherwise the existing type is kept. Values that do not fit their
    column become NULL and are counted in ``schema_json["last_load"]``. Without a primary key rows are
    appended (``replace=True`` empties the table first).
    """
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None or kb.org_id != org_id:
        raise KbNotFound("Base de conocimiento no encontrada")
    if not columns:
        raise KnowledgeError("La tabla necesita al menos una columna", code="invalid_columns")
    name = _table_name(table)
    specs = [_spec_from_dict(c) for c in columns]
    sanitized = ct.unique_identifiers([s.name for s in specs])
    source_names = [s.name for s in specs]
    for spec, clean in zip(specs, sanitized, strict=True):
        spec.name = clean
    name_map = dict(zip(source_names, sanitized, strict=True))
    pk: list[str] = []
    for key in primary_key:
        if key not in name_map and key not in sanitized:
            raise KnowledgeError(f"La clave primaria {key} no está entre las columnas", code="invalid_primary_key")
        pk.append(name_map.get(key, key))
    for spec in specs:
        spec.pk = spec.name in pk

    await _lock(session, kb.id, name)
    meta = (
        await session.execute(select(KbTable).where(KbTable.kb_id == kb.id, KbTable.name == name).with_for_update())
    ).scalar_one_or_none()
    existing = await _existing_columns(session, kb.schema_name, name)
    target = _q(kb.schema_name, name)
    if not existing:
        await _create_table(session, kb, name, specs, pk)
        final_types = [s.type for s in specs]
    else:
        previous_pk = list((meta.schema_json or {}).get("primary_key", [])) if meta else []
        if meta is not None and sorted(previous_pk) != sorted(pk):
            raise KnowledgeError(
                "La clave primaria no coincide con la de la tabla existente",
                code="primary_key_mismatch",
                details={"existing": previous_pk, "received": pk},
            )
        final_types = []
        for spec in specs:
            if spec.name not in existing:
                await session.execute(
                    text(f"ALTER TABLE {target} ADD COLUMN {quote_ident(spec.name)} {ct.PG_TYPES[spec.type]}")
                )
                final_types.append(spec.type)
                continue
            current = ct.PG_TO_LOGICAL.get(existing[spec.name], "text")
            if current != spec.type and not spec.pk:
                converted = await _try_convert(session, kb, name, spec.name, spec.type)
                final_types.append(spec.type if converted else current)
            else:
                final_types.append(current)
            spec.type = final_types[-1]
    if replace:
        await session.execute(text(f"DELETE FROM {target}"))
    names = [s.name for s in specs]
    matrix = [[row.get(src, row.get(clean)) for src, clean in zip(source_names, names, strict=True)] for row in rows]
    stats = await _load_rows(session, kb, name, names, list(final_types), matrix, pk)

    all_columns = await _existing_columns(session, kb.schema_name, name)
    previous = {c["name"]: c for c in (meta.schema_json or {}).get("columns", [])} if meta else {}
    column_json: list[dict[str, Any]] = []
    for col_name, data_type in all_columns.items():
        if col_name == ct.ROW_ID:
            continue
        spec = next((s for s in specs if s.name == col_name), None)
        if spec is not None:
            column_json.append(spec.to_json())
        elif col_name in previous:
            column_json.append(previous[col_name])
        else:
            column_json.append({"name": col_name, "type": ct.PG_TO_LOGICAL.get(data_type, "text"), "nullable": True})
    schema_json = {
        **((meta.schema_json or {}) if meta else {}),
        "columns": column_json,
        "primary_key": pk,
        "last_load": stats.to_json(),
    }
    row_count = await _row_count(session, kb, name)
    if meta is None:
        meta = KbTable(
            org_id=kb.org_id,
            kb_id=kb.id,
            name=name,
            description=description or "",
            schema_json=schema_json,
            row_count=row_count,
            source=source,
            sync_id=sync_id,
        )
        session.add(meta)
    else:
        meta.schema_json = schema_json
        meta.row_count = row_count
        meta.source = source
        meta.sync_id = sync_id or meta.sync_id
        if description is not None:
            meta.description = description
    await session.flush()
    return meta


async def _conversion_failures(
    session: AsyncSession, kb: KnowledgeBase, table: str, column: str, logical: str
) -> tuple[int, list[str]]:
    col = quote_ident(column)
    expr = ct.CONVERSIONS[logical].format(col=col)
    target = _q(kb.schema_name, table)
    failures = int(
        (
            await session.execute(text(f"SELECT count(*) FROM {target} WHERE {col} IS NOT NULL AND ({expr}) IS NULL"))
        ).scalar_one()
    )
    examples: list[str] = []
    if failures:
        rows = await session.execute(
            text(f"SELECT DISTINCT {col}::text FROM {target} WHERE {col} IS NOT NULL AND ({expr}) IS NULL LIMIT 5")
        )
        examples = [str(r[0]) for r in rows]
    return failures, examples


async def _try_convert(session: AsyncSession, kb: KnowledgeBase, table: str, column: str, logical: str) -> bool:
    failures, _ = await _conversion_failures(session, kb, table, column, logical)
    if failures:
        return False
    await _alter_type(session, kb, table, column, logical)
    return True


async def _alter_type(session: AsyncSession, kb: KnowledgeBase, table: str, column: str, logical: str) -> None:
    col = quote_ident(column)
    expr = ct.CONVERSIONS[logical].format(col=col)
    await session.execute(
        text(f"ALTER TABLE {_q(kb.schema_name, table)} ALTER COLUMN {col} TYPE {ct.PG_TYPES[logical]} USING {expr}")
    )


async def alter_column_type(
    session: AsyncSession, kb: KnowledgeBase, table: KbTable, column: str, new_type: str, *, force: bool = False
) -> KbTable:
    """Change a column's type (owner session). Without ``force``, refuses when values would be lost."""
    try:
        logical = ct.logical_type(new_type)
    except ct.CoercionError as exc:
        raise KnowledgeError(str(exc), code="invalid_column_type") from exc
    cols = table_columns(table)
    target_col = next((c for c in cols if c["name"] == column), None)
    if target_col is None:
        raise KnowledgeError("Columna no encontrada", code="column_not_found", status=404)
    if column in (table.schema_json or {}).get("primary_key", []):
        raise KnowledgeError("No se puede cambiar el tipo de la clave primaria", code="primary_key_type")
    await _lock(session, kb.id, table.name)
    if target_col["type"] == logical:
        return table
    failures, examples = await _conversion_failures(session, kb, table.name, column, logical)
    if failures and not force:
        raise KnowledgeError(
            f"{failures} valores no se pueden convertir a {logical}",
            code="type_conversion_failed",
            status=422,
            details={"failures": failures, "examples": examples, "type": logical},
        )
    await _alter_type(session, kb, table.name, column, logical)
    schema_json = dict(table.schema_json or {})
    schema_json["columns"] = [{**c, "type": logical} if c["name"] == column else c for c in cols]
    table.schema_json = schema_json
    await session.flush()
    return table


async def create_table_from_parsed(
    session: AsyncSession, *, kb: KnowledgeBase, file: KbFile, parsed: ParsedTable
) -> KbTable:
    """Create (or replace, when re-ingesting the same file) a table from an uploaded CSV/Excel sheet."""
    base = _table_name(parsed.name)
    names = ct.unique_identifiers(parsed.columns)
    types = ct.infer_columns(parsed.columns, parsed.rows)
    name = base
    n = 2
    while True:
        await _lock(session, kb.id, name)
        meta = (
            await session.execute(select(KbTable).where(KbTable.kb_id == kb.id, KbTable.name == name).with_for_update())
        ).scalar_one_or_none()
        existing = await _existing_columns(session, kb.schema_name, name)
        same_file = (
            meta is not None
            and (meta.schema_json or {}).get("file_id") == str(file.id)
            and ((meta.schema_json or {}).get("sheet") == parsed.sheet)
        )
        if same_file and meta is not None:
            await session.execute(text(f"DROP TABLE IF EXISTS {_q(kb.schema_name, name)}"))
            await session.delete(meta)
            await session.flush()
            break
        if meta is None and not existing:
            break
        suffix = f"_{n}"
        name = base[: 63 - len(suffix)] + suffix
        n += 1
    specs = [
        ct.ColumnSpec(name=clean, type=logical, source_name=original)
        for clean, logical, original in zip(names, types, parsed.columns, strict=True)
    ]
    await _create_table(session, kb, name, specs, [])
    stats = await _load_rows(session, kb, name, names, list(types), parsed.rows, [])
    table = KbTable(
        org_id=kb.org_id,
        kb_id=kb.id,
        name=name,
        description=f"Importada de {file.filename}" + (f" (hoja {parsed.sheet})" if parsed.sheet else ""),
        schema_json={
            "columns": [s.to_json() for s in specs],
            "primary_key": [],
            "file_id": str(file.id),
            "sheet": parsed.sheet,
            "last_load": stats.to_json(),
        },
        row_count=await _row_count(session, kb, name),
        source="upload",
    )
    session.add(table)
    await session.flush()
    return table


async def drop_table(session: AsyncSession, kb: KnowledgeBase, table: KbTable) -> None:
    await _lock(session, kb.id, table.name)
    await session.execute(text(f"DROP TABLE IF EXISTS {_q(kb.schema_name, table.name)}"))
    await session.execute(
        text("UPDATE public.kb_files SET table_id = NULL WHERE kb_id = :kb AND table_id = :t"),
        {"kb": kb.id, "t": table.id},
    )
    await session.delete(table)
    await session.flush()


# ---------------------------------------------------------------------------------------------- reading


@dataclass(slots=True)
class RowFilter:
    column: str
    op: FilterOp
    value: Any = None


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def build_rows_query(
    table: KbTable,
    *,
    filters: list[RowFilter],
    sort: str | None,
    order: Literal["asc", "desc"],
    limit: int,
    offset: int,
) -> tuple[str, str, list[Any]]:
    """(rows SQL, count SQL, params) over the table's unqualified name (so policies shadow it)."""
    types = column_types(table)
    columns = [c["name"] for c in table_columns(table)]
    pk = table_primary_key(table)
    select_cols = ([ct.ROW_ID] if ct.ROW_ID in types else []) + columns
    params: list[Any] = []
    where: list[str] = []
    for f in filters:
        if f.column not in types:
            raise KnowledgeError(f"Columna desconocida: {f.column}", code="invalid_filter")
        col = quote_ident(f.column)
        if f.op == "is_null":
            where.append(f"{col} IS NULL")
        elif f.op == "not_null":
            where.append(f"{col} IS NOT NULL")
        elif f.op in ("contains", "starts"):
            params.append(("%" if f.op == "contains" else "") + _escape_like(str(f.value or "")) + "%")
            where.append(f"{col}::text ILIKE ${len(params)}")
        elif f.op in _FILTER_SQL:
            if f.value is None or f.value == "":
                raise KnowledgeError(f"Falta el valor del filtro sobre {f.column}", code="invalid_filter")
            params.append(json.dumps(f.value) if isinstance(f.value, dict | list) else str(f.value))
            cast = ct.PG_TYPES.get(types[f.column], "text")
            where.append(f"{col} {_FILTER_SQL[f.op]} ${len(params)}::{cast}")
        else:
            raise KnowledgeError(f"Operador no válido: {f.op}", code="invalid_filter")
    relation = quote_ident(table.name)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    if sort is not None and sort not in types:
        raise KnowledgeError(f"Columna desconocida: {sort}", code="invalid_sort")
    order_cols = [sort] if sort else pk
    direction = "DESC" if order == "desc" else "ASC"
    order_sql = ", ".join(f"{quote_ident(c)} {direction} NULLS LAST" for c in order_cols)
    if sort and sort not in pk:
        order_sql += ", " + ", ".join(f"{quote_ident(c)} ASC" for c in pk)
    select_sql = ", ".join(quote_ident(c) for c in select_cols)
    rows_sql = (
        f"SELECT {select_sql} FROM {relation}{where_sql} ORDER BY {order_sql} "
        f"LIMIT {max(1, min(limit, 500))} OFFSET {max(0, offset)}"
    )
    count_sql = f"SELECT count(*) AS total FROM {relation}{where_sql}"
    return rows_sql, count_sql, params


async def query_rows(
    kb: KnowledgeBase,
    table: KbTable,
    *,
    role: str | None,
    filters: list[RowFilter],
    sort: str | None = None,
    order: Literal["asc", "desc"] = "asc",
    limit: int = 50,
    offset: int = 0,
    break_glass: bool = False,
) -> tuple[SqlResult, int]:
    rows_sql, count_sql, params = build_rows_query(
        table, filters=filters, sort=sort, order=order, limit=limit, offset=offset
    )
    result = await run_readonly(kb_id=kb.id, sql=rows_sql, params=params, role=role, limit=500, break_glass=break_glass)
    count = await run_readonly(kb_id=kb.id, sql=count_sql, params=params, role=role, limit=1, break_glass=break_glass)
    total = int(count.rows[0][0]) if count.rows else 0
    return result, total


async def update_cell(
    session: AsyncSession,
    kb: KnowledgeBase,
    table: KbTable,
    *,
    pk: dict[str, Any],
    column: str,
    value: Any,
) -> dict[str, Any]:
    """Update one cell by primary key (owner session); returns the updated row."""
    types = column_types(table)
    if column not in types or column == ct.ROW_ID:
        raise KnowledgeError("Columna no editable", code="column_not_editable")
    keys = table_primary_key(table)
    if column in keys and keys != [ct.ROW_ID]:
        raise KnowledgeError("La clave primaria no se puede editar", code="column_not_editable")
    if sorted(pk) != sorted(keys):
        raise KnowledgeError("Identifica la fila con su clave primaria", code="invalid_row_key", details={"pk": keys})
    try:
        new_value = ct.coerce(value, types[column])
        pk_values = {k: ct.coerce(pk[k], types[k]) for k in keys}
    except ct.CoercionError as exc:
        raise KnowledgeError(str(exc), code="invalid_value", status=422) from exc
    params: dict[str, Any] = {
        "v": json.dumps(new_value) if types[column] == "json" and new_value is not None else new_value
    }
    conditions = []
    for i, key in enumerate(keys):
        params[f"k{i}"] = pk_values[key]
        conditions.append(f"{quote_ident(key)} = CAST(:k{i} AS {ct.PG_TYPES[types[key]]})")
    await _lock(session, kb.id, table.name)
    result = await session.execute(
        text(
            f"UPDATE {_q(kb.schema_name, table.name)} SET {quote_ident(column)} = "
            f"CAST(:v AS {ct.PG_TYPES[types[column]]}) WHERE " + " AND ".join(conditions) + " RETURNING *"
        ),
        params,
    )
    row = result.mappings().first()
    if row is None:
        raise KnowledgeError("Fila no encontrada", code="row_not_found", status=404)
    return {str(k): jsonable(v) for k, v in row.items()}
