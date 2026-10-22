"""Database engines for PostgreSQL (psycopg 3), MySQL/MariaDB (PyMySQL) and SQL Server (python-tds).

Only the standard library and the drivers are imported here, so the on-prem connector agent bundles this
module without the rest of the platform. Every engine:

* runs user SQL through :func:`guard.check_read_only` and inside a read-only transaction (PostgreSQL,
  MySQL) or a transaction that is always rolled back (SQL Server), with a statement timeout and a row limit;
* introspects schemas (columns, types, nullability, defaults, primary and foreign keys, comments);
* fetches table batches for syncs with keyset pagination (``fetch_batch``).

Results are JSON-safe (see :mod:`values`), identical whether they come from the control plane or an agent.
"""

from __future__ import annotations

import abc
import asyncio
import ssl
import time
import uuid
from typing import Any

from . import values as V
from .dsn import Dialect, ParsedDsn, parse_dsn, truthy
from .guard import StatementRejected, check_read_only, to_format_params

DEFAULT_TIMEOUT_MS = 15_000
SYNC_TIMEOUT_MS = 120_000
CONNECT_TIMEOUT_S = 10

STREAMING_KEYWORDS = ("select", "with", "values", "table")


class SqlError(Exception):
    """A database error with a message that is safe to return to the user."""

    def __init__(self, message: str, *, code: str = "sql_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def _first_word(sql: str) -> str:
    for token in sql.strip().split():
        return token.lower().lstrip("(")
    return ""


def _result(columns: list[dict[str, str]], rows: list[Any], limit: int, started: float) -> dict[str, Any]:
    truncated = len(rows) > limit
    rows = rows[:limit]
    return {
        "columns": columns,
        "rows": [[V.to_json_value(v) for v in row] for row in rows],
        "row_count": len(rows),
        "truncated": truncated,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }


def _keyset_condition(quote: Any, keys: list[str], placeholder: str = "%s") -> str:
    """``(k1 > ?) OR (k1 = ? AND k2 > ?) OR …`` — portable keyset pagination (no row constructors)."""
    parts: list[str] = []
    for i in range(len(keys)):
        eqs = [f"{quote(k)} = {placeholder}" for k in keys[:i]]
        parts.append("(" + " AND ".join([*eqs, f"{quote(keys[i])} > {placeholder}"]) + ")")
    return "(" + " OR ".join(parts) + ")"


def _keyset_params(after: list[Any]) -> list[Any]:
    params: list[Any] = []
    for i in range(len(after)):
        params.extend(after[:i])
        params.append(after[i])
    return params


class SqlEngine(abc.ABC):
    dialect: Dialect

    def __init__(self, dsn: str, *, read_only: bool = True) -> None:
        self.dsn = dsn
        self.read_only = read_only
        self.parsed: ParsedDsn = parse_dsn(dsn, self.dialect)

    @property
    def host(self) -> str:
        return self.parsed.host

    # -- identifiers
    @abc.abstractmethod
    def quote(self, ident: str) -> str: ...

    def qualified(self, schema: str | None, table: str) -> str:
        return f"{self.quote(schema)}.{self.quote(table)}" if schema else self.quote(table)

    # -- operations
    @abc.abstractmethod
    async def ping(self) -> dict[str, Any]: ...

    @abc.abstractmethod
    async def _run(
        self, sql: str, params: list[Any] | None, *, limit: int, timeout_ms: int, write: bool
    ) -> dict[str, Any]: ...

    async def query(
        self,
        sql: str,
        params: list[Any] | None = None,
        *,
        limit: int = 1000,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        allow_write: bool = False,
    ) -> dict[str, Any]:
        write = allow_write and not self.read_only
        try:
            statement = sql.strip().rstrip(";") if write else check_read_only(sql, self.dialect)
            statement, bound = to_format_params(statement, params, self.dialect)
        except StatementRejected as exc:
            raise SqlError(str(exc), code="read_only") from exc
        limit = max(1, min(int(limit), 50_000))
        return await self._run(statement, bound, limit=limit, timeout_ms=timeout_ms, write=write)

    @abc.abstractmethod
    async def introspect(self, *, schemas: list[str] | None = None) -> dict[str, Any]: ...

    async def fetch_batch(
        self,
        *,
        schema: str | None,
        table: str,
        columns: list[str],
        key_columns: list[str],
        key_types: list[str],
        after: list[Any] | None = None,
        lower_bound: Any = None,
        limit: int = 500,
        timeout_ms: int = SYNC_TIMEOUT_MS,
    ) -> dict[str, Any]:
        """One page of ``table`` ordered by ``key_columns``; ``lower_bound`` applies ``key_columns[0] >= value``."""
        if not key_columns:
            raise SqlError("La sincronización necesita una clave (primaria o de cursor)", code="no_key")
        typed_after = [V.revive(t, v) for t, v in zip(key_types, after or [], strict=False)] if after else None
        conds: list[str] = [f"{self.quote(key_columns[0])} IS NOT NULL"]
        params: list[Any] = []
        if lower_bound is not None:
            conds.append(f"{self.quote(key_columns[0])} >= %s")
            params.append(V.revive(key_types[0], lower_bound))
        if typed_after:
            conds.append(_keyset_condition(self.quote, key_columns[: len(typed_after)]))
            params.extend(_keyset_params(typed_after))
        select_cols = ", ".join(self.quote(c) for c in columns)
        order = ", ".join(self.quote(k) for k in key_columns)
        sql = self._select_page(select_cols, self.qualified(schema, table), " AND ".join(conds), order, limit)
        raw = await self._run(sql, params, limit=limit, timeout_ms=timeout_ms, write=False)
        names = [c["name"] for c in raw["columns"]]
        rows = [dict(zip(names, r, strict=True)) for r in raw["rows"]]
        last_key = [rows[-1].get(k) for k in key_columns] if rows else None
        return {"columns": names, "rows": rows, "last_key": last_key, "elapsed_ms": raw["elapsed_ms"]}

    def _select_page(self, cols: str, source: str, where: str, order: str, limit: int) -> str:
        return f"SELECT {cols} FROM {source} WHERE {where} ORDER BY {order} LIMIT {int(limit)}"


# ============================================================================= PostgreSQL


class PostgresEngine(SqlEngine):
    dialect: Dialect = "postgresql"

    def quote(self, ident: str) -> str:
        return '"' + ident.replace('"', '""') + '"'

    def _conninfo(self) -> str:
        dsn = self.dsn.strip()
        for prefix in ("postgresql+psycopg://", "postgresql+asyncpg://", "postgres://"):
            if dsn.startswith(prefix):
                return "postgresql://" + dsn[len(prefix) :]
        return dsn

    async def _connect(self) -> Any:
        import psycopg

        try:
            return await psycopg.AsyncConnection.connect(
                self._conninfo(),
                autocommit=True,
                connect_timeout=CONNECT_TIMEOUT_S,
                application_name="messer-connector",
            )
        except psycopg.OperationalError as exc:
            raise SqlError(f"No se puede conectar a PostgreSQL: {_pg_message(exc)}", code="connect_failed") from exc

    async def ping(self) -> dict[str, Any]:
        conn = await self._connect()
        try:
            cur = await conn.execute("select version(), current_database(), current_user")
            row = await cur.fetchone()
            assert row is not None
            return {"version": row[0], "database": row[1], "user": row[2]}
        finally:
            await conn.close()

    async def _run(
        self, sql: str, params: list[Any] | None, *, limit: int, timeout_ms: int, write: bool
    ) -> dict[str, Any]:
        import psycopg

        started = time.monotonic()
        conn = await self._connect()
        try:
            await conn.set_read_only(not write)
            try:
                async with conn.transaction(force_rollback=not write):
                    await conn.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
                    await conn.execute(f"SET LOCAL idle_in_transaction_session_timeout = {int(timeout_ms) + 5000}")
                    if not write and _first_word(sql) in STREAMING_KEYWORDS:
                        cur = conn.cursor(name=f"messer_{uuid.uuid4().hex[:12]}")
                        try:
                            await cur.execute(sql, params)
                            rows = await cur.fetchmany(limit + 1)
                            description = cur.description or []
                        finally:
                            await cur.close()
                    else:
                        cur = conn.cursor()
                        await cur.execute(sql, params)
                        description = cur.description or []
                        rows = await cur.fetchmany(limit + 1) if cur.description else []
                    columns = [{"name": d.name, "type": _pg_type_name(conn, d.type_code)} for d in description]
                    result = _result(columns, list(rows), limit, started)
                    if write and not description:
                        result["affected_rows"] = cur.rowcount
                    return result
            except psycopg.errors.ReadOnlySqlTransaction as exc:
                raise SqlError(
                    "La conexión es de solo lectura: la sentencia intenta modificar datos", code="read_only"
                ) from exc
            except psycopg.errors.QueryCanceled as exc:
                raise SqlError(f"La consulta ha superado el tiempo máximo ({timeout_ms} ms)", code="timeout") from exc
            except psycopg.Error as exc:
                raise SqlError(_pg_message(exc)) from exc
        finally:
            await conn.close()

    async def introspect(self, *, schemas: list[str] | None = None) -> dict[str, Any]:
        import psycopg

        conn = await self._connect()
        try:
            await conn.set_read_only(True)
            async with conn.transaction(force_rollback=True):
                await conn.execute("SET LOCAL statement_timeout = 60000")
                schema_filter = "AND n.nspname = ANY(%s)" if schemas else ""
                args: list[Any] = [schemas] if schemas else []
                cur = await conn.execute(
                    f"""
                    SELECT n.nspname, c.relname, c.relkind, obj_description(c.oid, 'pg_class'),
                           c.reltuples::bigint, a.attname, format_type(a.atttypid, a.atttypmod), t.typname,
                           NOT a.attnotnull, pg_get_expr(d.adbin, d.adrelid), col_description(c.oid, a.attnum)
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
                    JOIN pg_type t ON t.oid = a.atttypid
                    LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
                    WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f')
                      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
                      AND n.nspname !~ '^pg_'
                      AND has_table_privilege(c.oid, 'SELECT')
                      {schema_filter}
                    ORDER BY n.nspname, c.relname, a.attnum
                    """,
                    args,
                )
                column_rows = await cur.fetchall()
                cur = await conn.execute(
                    f"""
                    SELECT n.nspname, c.relname, con.contype, con.conname,
                           array(SELECT a.attname FROM unnest(con.conkey) WITH ORDINALITY k(num, ord)
                                 JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.num ORDER BY k.ord),
                           fn.nspname, fc.relname,
                           array(SELECT a.attname FROM unnest(con.confkey) WITH ORDINALITY k(num, ord)
                                 JOIN pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k.num ORDER BY k.ord)
                    FROM pg_constraint con
                    JOIN pg_class c ON c.oid = con.conrelid
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    LEFT JOIN pg_class fc ON fc.oid = con.confrelid
                    LEFT JOIN pg_namespace fn ON fn.oid = fc.relnamespace
                    WHERE con.contype IN ('p', 'f')
                      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
                      AND n.nspname !~ '^pg_'
                      {schema_filter}
                    ORDER BY n.nspname, c.relname, con.conname
                    """,
                    args,
                )
                constraint_rows = await cur.fetchall()
        except psycopg.Error as exc:
            raise SqlError(_pg_message(exc)) from exc
        finally:
            await conn.close()

        kinds = {"r": "table", "p": "table", "v": "view", "m": "materialized_view", "f": "foreign_table"}
        tables: dict[tuple[str, str], dict[str, Any]] = {}
        for schema, name, kind, tcomment, estimate, col, full_type, udt, nullable, default, ccomment in column_rows:
            entry = tables.setdefault(
                (schema, name),
                {
                    "schema": schema,
                    "name": name,
                    "kind": kinds.get(kind, "table"),
                    "comment": tcomment,
                    "row_estimate": max(int(estimate or 0), 0),
                    "columns": [],
                    "primary_key": [],
                    "foreign_keys": [],
                },
            )
            base = str(full_type).split("(")[0]
            entry["columns"].append(
                {
                    "name": col,
                    "type": full_type,
                    "kb_type": "json" if str(full_type).endswith("[]") else V.kb_type_postgres(base, udt),
                    "nullable": bool(nullable),
                    "default": default,
                    "comment": ccomment,
                    "pk": False,
                }
            )
        for schema, name, contype, conname, cols, ref_schema, ref_table, ref_cols in constraint_rows:
            entry = tables.get((schema, name))
            if entry is None:
                continue
            if contype == "p":
                entry["primary_key"] = list(cols)
            else:
                entry["foreign_keys"].append(
                    {
                        "name": conname,
                        "columns": list(cols),
                        "ref_schema": ref_schema,
                        "ref_table": ref_table,
                        "ref_columns": list(ref_cols),
                    }
                )
        return _finish_schema("postgresql", tables)


def _pg_type_name(conn: Any, oid: int) -> str:
    info = conn.adapters.types.get(oid)
    return str(info.name) if info is not None else str(oid)


def _pg_message(exc: Exception) -> str:
    diag = getattr(exc, "diag", None)
    primary = getattr(diag, "message_primary", None) if diag is not None else None
    if primary:
        return str(primary)[:500]
    text = str(exc).strip()
    return (text.splitlines()[0] if text else type(exc).__name__)[:500]


# ============================================================================= MySQL / MariaDB


class MySqlEngine(SqlEngine):
    dialect: Dialect = "mysql"

    def quote(self, ident: str) -> str:
        return "`" + ident.replace("`", "``") + "`"

    def _connect_sync(self, timeout_s: int) -> Any:
        import pymysql

        p = self.parsed
        kwargs: dict[str, Any] = {}
        mode = (p.options.get("ssl-mode") or p.options.get("ssl_mode") or p.options.get("sslmode") or "").lower()
        if truthy(p.options.get("ssl")) or mode in ("required", "require", "verify_ca", "verify_identity"):
            ctx = ssl.create_default_context()
            if mode in ("required", "require"):
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            kwargs["ssl"] = ctx
        try:
            return pymysql.connect(
                host=p.host,
                port=p.port,
                user=p.user,
                password=p.password,
                database=p.database or None,
                charset=p.options.get("charset", "utf8mb4"),
                connect_timeout=CONNECT_TIMEOUT_S,
                read_timeout=timeout_s,
                write_timeout=timeout_s,
                autocommit=False,
                **kwargs,
            )
        except pymysql.MySQLError as exc:
            raise SqlError(f"No se puede conectar a MySQL: {_mysql_message(exc)}", code="connect_failed") from exc

    async def ping(self) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            conn = self._connect_sync(15)
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT VERSION(), DATABASE(), CURRENT_USER()")
                    row = cur.fetchone()
                    assert row is not None
                    return {"version": row[0], "database": row[1], "user": row[2]}
            finally:
                conn.close()

        return await asyncio.to_thread(run)

    async def _run(
        self, sql: str, params: list[Any] | None, *, limit: int, timeout_ms: int, write: bool
    ) -> dict[str, Any]:
        import pymysql
        from pymysql.constants import FIELD_TYPE

        type_names = {v: k.lower() for k, v in vars(FIELD_TYPE).items() if k.isupper()}

        def run() -> dict[str, Any]:
            started = time.monotonic()
            conn = self._connect_sync(max(5, timeout_ms // 1000 + 5))
            try:
                with conn.cursor() as cur:
                    for stmt in (
                        f"SET SESSION max_execution_time = {int(timeout_ms)}",
                        f"SET SESSION max_statement_time = {max(1, int(timeout_ms) // 1000)}",
                    ):
                        try:
                            cur.execute(stmt)
                        except pymysql.MySQLError:
                            pass  # MySQL and MariaDB name the timeout differently
                    if not write:
                        cur.execute(f"SET SESSION sql_select_limit = {int(limit) + 1}")
                        cur.execute("START TRANSACTION READ ONLY")
                    try:
                        cur.execute(sql, params)
                        description = cur.description or []
                        rows = list(cur.fetchmany(limit + 1)) if cur.description else []
                        columns = [{"name": d[0], "type": type_names.get(d[1], str(d[1]))} for d in description]
                        result = _result(columns, rows, limit, started)
                        if write:
                            if not description:
                                result["affected_rows"] = cur.rowcount
                            conn.commit()
                        return result
                    finally:
                        if not write:
                            conn.rollback()
            except pymysql.MySQLError as exc:
                code = exc.args[0] if exc.args else 0
                if code == 1792:
                    raise SqlError(
                        "La conexión es de solo lectura: la sentencia intenta modificar datos", code="read_only"
                    ) from exc
                if code in (3024, 1969):
                    raise SqlError(
                        f"La consulta ha superado el tiempo máximo ({timeout_ms} ms)", code="timeout"
                    ) from exc
                raise SqlError(_mysql_message(exc)) from exc
            finally:
                conn.close()

        return await asyncio.to_thread(run)

    async def introspect(self, *, schemas: list[str] | None = None) -> dict[str, Any]:
        import pymysql

        target = schemas or ([self.parsed.database] if self.parsed.database else None)

        def run() -> dict[str, Any]:
            conn = self._connect_sync(60)
            try:
                with conn.cursor() as cur:
                    cur.execute("START TRANSACTION READ ONLY")
                    if target:
                        marks = ", ".join(["%s"] * len(target))
                        where = f"c.TABLE_SCHEMA IN ({marks})"
                        args: list[Any] = list(target)
                    else:
                        where = "c.TABLE_SCHEMA NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')"
                        args = []
                    cur.execute(
                        f"""
                        SELECT c.TABLE_SCHEMA, c.TABLE_NAME, t.TABLE_TYPE, t.TABLE_COMMENT, t.TABLE_ROWS,
                               c.COLUMN_NAME, c.DATA_TYPE, c.COLUMN_TYPE, c.IS_NULLABLE, c.COLUMN_DEFAULT,
                               c.COLUMN_COMMENT
                        FROM information_schema.COLUMNS c
                        JOIN information_schema.TABLES t
                          ON t.TABLE_SCHEMA = c.TABLE_SCHEMA AND t.TABLE_NAME = c.TABLE_NAME
                        WHERE {where}
                        ORDER BY c.TABLE_SCHEMA, c.TABLE_NAME, c.ORDINAL_POSITION
                        """,
                        args,
                    )
                    column_rows = list(cur.fetchall())
                    cur.execute(
                        f"""
                        SELECT c.TABLE_SCHEMA, c.TABLE_NAME, c.CONSTRAINT_NAME, c.COLUMN_NAME,
                               c.REFERENCED_TABLE_SCHEMA, c.REFERENCED_TABLE_NAME, c.REFERENCED_COLUMN_NAME
                        FROM information_schema.KEY_COLUMN_USAGE c
                        WHERE {where} AND (c.CONSTRAINT_NAME = 'PRIMARY' OR c.REFERENCED_TABLE_NAME IS NOT NULL)
                        ORDER BY c.TABLE_SCHEMA, c.TABLE_NAME, c.CONSTRAINT_NAME, c.ORDINAL_POSITION
                        """,
                        args,
                    )
                    key_rows = list(cur.fetchall())
                    conn.rollback()
            except pymysql.MySQLError as exc:
                raise SqlError(_mysql_message(exc)) from exc
            finally:
                conn.close()

            tables: dict[tuple[str, str], dict[str, Any]] = {}
            for schema, name, ttype, tcomment, trows, col, dtype, ctype, nullable, default, ccomment in column_rows:
                entry = tables.setdefault(
                    (schema, name),
                    {
                        "schema": schema,
                        "name": name,
                        "kind": "view" if str(ttype).upper() == "VIEW" else "table",
                        "comment": tcomment or None,
                        "row_estimate": int(trows or 0),
                        "columns": [],
                        "primary_key": [],
                        "foreign_keys": [],
                    },
                )
                entry["columns"].append(
                    {
                        "name": col,
                        "type": ctype,
                        "kb_type": V.kb_type_mysql(str(dtype), str(ctype)),
                        "nullable": str(nullable).upper() == "YES",
                        "default": default,
                        "comment": ccomment or None,
                        "pk": False,
                    }
                )
            fks: dict[tuple[str, str, str], dict[str, Any]] = {}
            for schema, name, cname, col, rschema, rtable, rcol in key_rows:
                entry = tables.get((schema, name))
                if entry is None:
                    continue
                if cname == "PRIMARY":
                    entry["primary_key"].append(col)
                    continue
                fk = fks.get((schema, name, cname))
                if fk is None:
                    fk = {"name": cname, "columns": [], "ref_schema": rschema, "ref_table": rtable, "ref_columns": []}
                    fks[(schema, name, cname)] = fk
                    entry["foreign_keys"].append(fk)
                fk["columns"].append(col)
                fk["ref_columns"].append(rcol)
            return _finish_schema("mysql", tables)

        return await asyncio.to_thread(run)


def _mysql_message(exc: Exception) -> str:
    args = getattr(exc, "args", ())
    if len(args) >= 2:
        return str(args[1])[:500]
    return str(exc)[:500]


# ============================================================================= SQL Server


class SqlServerEngine(SqlEngine):
    dialect: Dialect = "sqlserver"

    def quote(self, ident: str) -> str:
        return "[" + ident.replace("]", "]]") + "]"

    def _select_page(self, cols: str, source: str, where: str, order: str, limit: int) -> str:
        return f"SELECT TOP ({int(limit)}) {cols} FROM {source} WHERE {where} ORDER BY {order}"

    def _connect_sync(self, timeout_s: int) -> Any:
        import pytds

        p = self.parsed
        kwargs: dict[str, Any] = {}
        encrypt = (p.options.get("encrypt") or "").lower()
        if truthy(encrypt):
            try:
                import certifi

                kwargs["cafile"] = certifi.where()
            except ImportError:
                kwargs["cafile"] = ssl.get_default_verify_paths().cafile
            kwargs["validate_host"] = not truthy(p.options.get("trustservercertificate"))
        try:
            return pytds.connect(
                dsn=p.host,
                port=p.port,
                database=p.database or None,
                user=p.user,
                password=p.password,
                timeout=timeout_s,
                login_timeout=CONNECT_TIMEOUT_S,
                autocommit=False,
                readonly=self.read_only,
                appname="messer-connector",
                **kwargs,
            )
        except Exception as exc:  # pytds raises several unrelated exception types on connect
            raise SqlError(f"No se puede conectar a SQL Server: {str(exc)[:300]}", code="connect_failed") from exc

    async def ping(self) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            conn = self._connect_sync(15)
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT @@VERSION, DB_NAME(), SUSER_SNAME()")
                    row = cur.fetchone()
                    assert row is not None
                    return {"version": str(row[0]).splitlines()[0], "database": row[1], "user": row[2]}
            finally:
                conn.rollback()
                conn.close()

        return await asyncio.to_thread(run)

    async def _run(
        self, sql: str, params: list[Any] | None, *, limit: int, timeout_ms: int, write: bool
    ) -> dict[str, Any]:
        import pytds

        def run() -> dict[str, Any]:
            started = time.monotonic()
            conn = self._connect_sync(max(5, timeout_ms // 1000 + 1))
            try:
                with conn.cursor() as cur:
                    cur.execute(f"SET LOCK_TIMEOUT {int(timeout_ms)}")
                    if not write:
                        cur.execute(f"SET ROWCOUNT {int(limit) + 1}")
                    cur.execute(sql, params)
                    description = cur.description or []
                    rows = list(cur.fetchmany(limit + 1)) if cur.description else []
                    columns = [{"name": d[0], "type": str(d[1])} for d in description]
                    result = _result(columns, rows, limit, started)
                    if write:
                        if not description:
                            result["affected_rows"] = cur.rowcount
                        conn.commit()
                    return result
            except pytds.Error as exc:
                message = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
                if "timeout" in message.lower():
                    raise SqlError(
                        f"La consulta ha superado el tiempo máximo ({timeout_ms} ms)", code="timeout"
                    ) from exc
                raise SqlError(message[:500]) from exc
            except TimeoutError as exc:
                raise SqlError(f"La consulta ha superado el tiempo máximo ({timeout_ms} ms)", code="timeout") from exc
            finally:
                # Read-only enforcement on SQL Server: whatever the statement did is rolled back.
                if not write:
                    try:
                        conn.rollback()
                    except Exception:  # noqa: S110 - connection already broken; closing below
                        pass
                conn.close()

        return await asyncio.to_thread(run)

    async def introspect(self, *, schemas: list[str] | None = None) -> dict[str, Any]:
        import pytds

        def run() -> dict[str, Any]:
            conn = self._connect_sync(60)
            try:
                with conn.cursor() as cur:
                    if schemas:
                        marks = ", ".join(["%s"] * len(schemas))
                        sfilter = f"AND s.name IN ({marks})"
                        args: list[Any] = list(schemas)
                    else:
                        sfilter = "AND s.name NOT IN ('sys', 'INFORMATION_SCHEMA')"
                        args = []
                    cur.execute(
                        f"""
                        SELECT s.name, o.name, o.type, CAST(ep.value AS nvarchar(4000)),
                               (SELECT SUM(p.rows) FROM sys.partitions p WHERE p.object_id = o.object_id AND p.index_id IN (0, 1)),
                               c.name, TYPE_NAME(c.system_type_id), TYPE_NAME(c.user_type_id), c.max_length,
                               c.precision, c.scale, c.is_nullable, OBJECT_DEFINITION(c.default_object_id),
                               CAST(cep.value AS nvarchar(4000))
                        FROM sys.objects o
                        JOIN sys.schemas s ON s.schema_id = o.schema_id
                        JOIN sys.columns c ON c.object_id = o.object_id
                        LEFT JOIN sys.extended_properties ep
                          ON ep.class = 1 AND ep.major_id = o.object_id AND ep.minor_id = 0 AND ep.name = 'MS_Description'
                        LEFT JOIN sys.extended_properties cep
                          ON cep.class = 1 AND cep.major_id = o.object_id AND cep.minor_id = c.column_id
                         AND cep.name = 'MS_Description'
                        WHERE o.type IN ('U', 'V') AND o.is_ms_shipped = 0 {sfilter}
                        ORDER BY s.name, o.name, c.column_id
                        """,
                        args,
                    )
                    column_rows = list(cur.fetchall())
                    cur.execute(
                        f"""
                        SELECT s.name, t.name, c.name
                        FROM sys.indexes i
                        JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
                        JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
                        JOIN sys.tables t ON t.object_id = i.object_id
                        JOIN sys.schemas s ON s.schema_id = t.schema_id
                        WHERE i.is_primary_key = 1 {sfilter}
                        ORDER BY s.name, t.name, ic.key_ordinal
                        """,
                        args,
                    )
                    pk_rows = list(cur.fetchall())
                    cur.execute(
                        f"""
                        SELECT fk.name, s.name, t.name, c.name, rs.name, rt.name, rc.name
                        FROM sys.foreign_keys fk
                        JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
                        JOIN sys.tables t ON t.object_id = fkc.parent_object_id
                        JOIN sys.schemas s ON s.schema_id = t.schema_id
                        JOIN sys.columns c ON c.object_id = fkc.parent_object_id AND c.column_id = fkc.parent_column_id
                        JOIN sys.tables rt ON rt.object_id = fkc.referenced_object_id
                        JOIN sys.schemas rs ON rs.schema_id = rt.schema_id
                        JOIN sys.columns rc
                          ON rc.object_id = fkc.referenced_object_id AND rc.column_id = fkc.referenced_column_id
                        WHERE 1 = 1 {sfilter}
                        ORDER BY fk.name, fkc.constraint_column_id
                        """,
                        args,
                    )
                    fk_rows = list(cur.fetchall())
            except pytds.Error as exc:
                raise SqlError(
                    str(exc).strip().splitlines()[0][:500] if str(exc).strip() else "SQL Server error"
                ) from exc
            finally:
                conn.rollback()
                conn.close()

            tables: dict[tuple[str, str], dict[str, Any]] = {}
            for (
                schema,
                name,
                otype,
                tcomment,
                rows,
                col,
                base_type,
                user_type,
                max_len,
                prec,
                scale,
                nullable,
                default,
                ccomment,
            ) in column_rows:
                entry = tables.setdefault(
                    (schema, name),
                    {
                        "schema": schema,
                        "name": name,
                        "kind": "view" if str(otype).strip() == "V" else "table",
                        "comment": tcomment,
                        "row_estimate": int(rows or 0),
                        "columns": [],
                        "primary_key": [],
                        "foreign_keys": [],
                    },
                )
                entry["columns"].append(
                    {
                        "name": col,
                        "type": _mssql_type(str(user_type or base_type), int(max_len or 0), prec, scale),
                        "kb_type": V.kb_type_sqlserver(str(base_type)),
                        "nullable": bool(nullable),
                        "default": default,
                        "comment": ccomment,
                        "pk": False,
                    }
                )
            for schema, name, col in pk_rows:
                entry = tables.get((schema, name))
                if entry is not None:
                    entry["primary_key"].append(col)
            fks: dict[tuple[str, str, str], dict[str, Any]] = {}
            for fname, schema, name, col, rschema, rtable, rcol in fk_rows:
                entry = tables.get((schema, name))
                if entry is None:
                    continue
                fk = fks.get((schema, name, fname))
                if fk is None:
                    fk = {"name": fname, "columns": [], "ref_schema": rschema, "ref_table": rtable, "ref_columns": []}
                    fks[(schema, name, fname)] = fk
                    entry["foreign_keys"].append(fk)
                fk["columns"].append(col)
                fk["ref_columns"].append(rcol)
            return _finish_schema("sqlserver", tables)

        return await asyncio.to_thread(run)


def _mssql_type(name: str, max_len: int, precision: Any, scale: Any) -> str:
    lowered = name.lower()
    if lowered in ("varchar", "char", "varbinary", "binary"):
        return f"{name}({'max' if max_len == -1 else max_len})"
    if lowered in ("nvarchar", "nchar"):
        return f"{name}({'max' if max_len == -1 else max_len // 2})"
    if lowered in ("decimal", "numeric"):
        return f"{name}({precision},{scale})"
    return name


# ============================================================================= helpers


def _finish_schema(dialect: str, tables: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    out = []
    for entry in tables.values():
        pk = set(entry["primary_key"])
        for col in entry["columns"]:
            col["pk"] = col["name"] in pk
        out.append(entry)
    return {"dialect": dialect, "tables": out, "table_count": len(out)}


ENGINES: dict[str, type[SqlEngine]] = {
    "postgresql": PostgresEngine,
    "mysql": MySqlEngine,
    "sqlserver": SqlServerEngine,
}


def create_engine(dialect: str, dsn: str, *, read_only: bool = True) -> SqlEngine:
    try:
        cls = ENGINES[dialect]
    except KeyError as exc:
        raise SqlError(f"Motor de base de datos no admitido: {dialect}", code="unsupported") from exc
    return cls(dsn, read_only=read_only)


def find_table(schema_doc: dict[str, Any], schema: str | None, table: str) -> dict[str, Any] | None:
    for entry in schema_doc.get("tables", []):
        if entry["name"] == table and (schema is None or entry["schema"] == schema):
            return entry
    return None
