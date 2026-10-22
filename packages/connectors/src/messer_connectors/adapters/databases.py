"""PostgreSQL, MySQL and SQL Server connectors: read-only queries, introspection and table syncs.

Connections hold the connection string encrypted in ``credentials.connection_string`` — or, when routed
through an on-prem agent (``connections.agent_id``), only the name of a source configured on the agent
(``config.agent_source``): the connection string then never leaves the customer's network.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar, Protocol

from ..agent_rpc import AgentSqlEngine
from ..base import (
    ActionSpec,
    Capabilities,
    ColumnDef,
    ConfigError,
    ConfigField,
    ConnectionContext,
    ConnectorAdapter,
    ConnectorError,
    ConnectorSpec,
    ReadOnlyViolation,
    Resource,
    SyncOutcome,
    SyncRequest,
    SyncSink,
    TestResult,
    obj_schema,
)
from ..http import check_public_host, private_networks_allowed
from ..registry import register
from ..sql import DsnError, SqlError, create_engine, find_table, parse_dsn
from ..sql import values as V
from ..util import kb_identifier, validate_args

MAX_QUERY_ROWS = 1000


class Engine(Protocol):
    async def ping(self) -> dict[str, Any]: ...

    async def query(
        self,
        sql: str,
        params: list[Any] | None = None,
        *,
        limit: int = 1000,
        timeout_ms: int = 15_000,
        allow_write: bool = False,
    ) -> dict[str, Any]: ...

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
        timeout_ms: int = 120_000,
    ) -> dict[str, Any]: ...


def _db_error(exc: SqlError) -> ConnectorError:
    if exc.code == "read_only":
        return ReadOnlyViolation(exc.message)
    return ConnectorError(exc.message, code=f"sql_{exc.code}" if not exc.code.startswith("sql") else exc.code)


def split_table_ref(ref: str) -> tuple[str | None, str]:
    """``table:schema.name`` / ``schema.name`` / ``name`` → (schema, name). Quoted parts keep their dots."""
    value = ref.removeprefix("table:")
    if value.startswith('"') or value.startswith("["):
        parts: list[str] = []
        current = ""
        quote: str | None = None
        for ch in value:
            if quote:
                if ch == quote:
                    quote = None
                else:
                    current += ch
            elif ch in ('"', "["):
                quote = '"' if ch == '"' else "]"
            elif ch == ".":
                parts.append(current)
                current = ""
            else:
                current += ch
        parts.append(current)
    else:
        parts = value.split(".", 1) if "." in value else [value]
    if len(parts) == 2:
        return parts[0] or None, parts[1]
    return None, parts[0]


class DatabaseAdapter(ConnectorAdapter):
    dialect: ClassVar[str]

    def actions(self) -> list[ActionSpec]:
        return [
            ActionSpec(
                name="query",
                title="Consulta SQL (solo lectura)",
                description=(
                    "Ejecuta una consulta SELECT de solo lectura. Usa $1, $2… para los parámetros. "
                    f"Devuelve como máximo {MAX_QUERY_ROWS} filas."
                ),
                input_schema=obj_schema(
                    {
                        "sql": {"type": "string", "minLength": 1, "description": "Consulta SELECT"},
                        "params": {"type": "array", "items": {}, "default": []},
                        "limit": {"type": "integer", "minimum": 1, "maximum": MAX_QUERY_ROWS, "default": 200},
                    },
                    ["sql"],
                ),
            ),
            ActionSpec(
                name="list_tables",
                title="Listar tablas",
                description="Lista tablas y vistas con su número aproximado de filas.",
                input_schema=obj_schema({"schema": {"type": "string"}}),
            ),
            ActionSpec(
                name="describe_table",
                title="Describir tabla",
                description="Columnas, tipos, clave primaria, claves foráneas y comentarios de una tabla.",
                input_schema=obj_schema({"table": {"type": "string", "description": "esquema.tabla"}}, ["table"]),
            ),
        ]

    def write_actions(self) -> list[ActionSpec]:
        return [
            ActionSpec(
                name="execute",
                title="Ejecutar sentencia de escritura",
                description="Ejecuta INSERT/UPDATE/DELETE. Solo disponible si la conexión no es de solo lectura.",
                input_schema=obj_schema(
                    {
                        "sql": {"type": "string", "minLength": 1},
                        "params": {"type": "array", "items": {}, "default": []},
                    },
                    ["sql"],
                ),
                side_effect=True,
            )
        ]

    def actions_for(self, ctx: ConnectionContext) -> list[ActionSpec]:
        if self._writes_enabled(ctx):
            return [*self.actions(), *self.write_actions()]
        return self.actions()

    def action(self, name: str) -> ActionSpec:
        for spec in [*self.actions(), *self.write_actions()]:
            if spec.name == name:
                return spec
        return super().action(name)

    @staticmethod
    def _writes_enabled(ctx: ConnectionContext) -> bool:
        return ctx.config.get("read_only") is False and ctx.agent_id is None

    # ------------------------------------------------------------------ config
    def validate_config(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        if config.get("agent_source"):
            return
        dsn = credentials.get("connection_string")
        if not dsn:
            raise ConfigError("Indica la cadena de conexión", details={"field": "connection_string"})
        try:
            parse_dsn(str(dsn), self.dialect)  # type: ignore[arg-type]
        except (DsnError, ValueError) as exc:
            raise ConfigError(f"Cadena de conexión no válida: {exc}", details={"field": "connection_string"}) from exc
        schemas = config.get("schemas")
        if schemas is not None and not (isinstance(schemas, list) and all(isinstance(s, str) for s in schemas)):
            raise ConfigError("«schemas» debe ser una lista de nombres", details={"field": "schemas"})

    def prepare(self, config: dict[str, Any], credentials: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        config = dict(config)
        config["read_only"] = config.get("read_only") is not False
        if credentials.get("connection_string"):
            parsed = parse_dsn(str(credentials["connection_string"]), self.dialect)  # type: ignore[arg-type]
            config["host"] = parsed.host
            config["port"] = parsed.port
            config["database"] = parsed.database
        return config, credentials

    async def engine(self, ctx: ConnectionContext) -> Engine:
        if ctx.agent_id is not None:
            source = ctx.config.get("agent_source")
            if not source:
                raise ConfigError("La conexión por agente necesita el nombre del origen configurado en el agente")
            return AgentSqlEngine(ctx.agent_id, source=str(source), dialect=self.dialect)
        dsn = ctx.credentials.get("connection_string")
        if not dsn:
            raise ConfigError("La conexión no tiene cadena de conexión")
        try:
            eng = create_engine(self.dialect, str(dsn), read_only=ctx.config.get("read_only") is not False)
        except (DsnError, ValueError) as exc:
            raise ConfigError(f"Cadena de conexión no válida: {exc}") from exc
        await asyncio.to_thread(check_public_host, eng.host, allow_private=private_networks_allowed())
        return eng

    def _schemas(self, ctx: ConnectionContext) -> list[str] | None:
        schemas = ctx.config.get("schemas")
        return [str(s) for s in schemas] if isinstance(schemas, list) and schemas else None

    # ------------------------------------------------------------------ operations
    async def test(self, ctx: ConnectionContext) -> TestResult:
        eng = await self.engine(ctx)
        try:
            info = await eng.ping()
        except SqlError as exc:
            return TestResult(ok=False, message=exc.message)
        read_only = ctx.config.get("read_only") is not False or ctx.agent_id is not None
        return TestResult(
            ok=True,
            message=f"Conectado a {self.spec.name}" + (" (solo lectura)" if read_only else ""),
            details={**info, "read_only": read_only},
        )

    async def run_action(self, ctx: ConnectionContext, action: str, args: dict[str, Any]) -> Any:
        spec = self.action(action)
        data = validate_args(spec, args)
        eng = await self.engine(ctx)
        try:
            if action == "query":
                return await eng.query(str(data["sql"]), list(data.get("params") or []), limit=int(data["limit"]))
            if action == "execute":
                if not self._writes_enabled(ctx):
                    raise ReadOnlyViolation("La conexión es de solo lectura")
                return await eng.query(str(data["sql"]), list(data.get("params") or []), limit=100, allow_write=True)
            if action == "list_tables":
                doc = await eng.introspect(schemas=[data["schema"]] if data.get("schema") else self._schemas(ctx))
                return [{k: t[k] for k in ("schema", "name", "kind", "row_estimate", "comment")} for t in doc["tables"]]
            if action == "describe_table":
                schema, name = split_table_ref(str(data["table"]))
                doc = await eng.introspect(schemas=[schema] if schema else self._schemas(ctx))
                table = find_table(doc, schema, name)
                if table is None:
                    raise ConnectorError(
                        f"La tabla {data['table']} no existe o no es accesible", code="table_not_found"
                    )
                return table
        except SqlError as exc:
            raise _db_error(exc) from exc
        return await super().run_action(ctx, action, args)

    async def introspect(self, ctx: ConnectionContext) -> dict[str, Any]:
        eng = await self.engine(ctx)
        try:
            return await eng.introspect(schemas=self._schemas(ctx))
        except SqlError as exc:
            raise _db_error(exc) from exc

    async def list_resources(self, ctx: ConnectionContext, parent: str | None = None) -> list[Resource]:
        doc = await self.introspect(ctx)
        return [
            Resource(
                id=f"table:{t['schema']}.{t['name']}",
                name=f"{t['schema']}.{t['name']}",
                kind=t["kind"],
                meta={
                    "primary_key": t["primary_key"],
                    "row_estimate": t["row_estimate"],
                    "columns": [{"name": c["name"], "type": c["type"], "kb_type": c["kb_type"]} for c in t["columns"]],
                },
            )
            for t in doc["tables"]
        ]

    async def sync(self, ctx: ConnectionContext, request: SyncRequest, sink: SyncSink) -> SyncOutcome:
        if not request.resource.startswith("table:"):
            raise ConfigError("El recurso debe ser «table:esquema.tabla»")
        schema, name = split_table_ref(request.resource)
        eng = await self.engine(ctx)
        try:
            doc = await eng.introspect(schemas=[schema] if schema else self._schemas(ctx))
        except SqlError as exc:
            raise _db_error(exc) from exc
        table = find_table(doc, schema, name)
        if table is None:
            raise ConfigError(f"La tabla {request.resource.removeprefix('table:')} no existe o no es accesible")
        schema = table["schema"]
        col_types = {c["name"]: c["kb_type"] for c in table["columns"]}
        wanted = request.options.get("columns")
        columns = [c for c in table["columns"] if not wanted or c["name"] in wanted]
        names = [c["name"] for c in columns]
        primary_key = [str(k) for k in (request.primary_key or table["primary_key"])]
        if not primary_key:
            raise ConfigError(
                "La tabla no tiene clave primaria: indica las columnas que identifican cada fila",
                details={"field": "primary_key"},
            )
        missing = [k for k in primary_key if k not in col_types]
        if missing:
            raise ConfigError(f"Columnas de clave inexistentes: {', '.join(missing)}")
        for k in primary_key:
            if k not in names:
                names.append(k)
                columns.append(next(c for c in table["columns"] if c["name"] == k))

        if request.mode == "incremental":
            cursor_field = request.cursor_field
            if not cursor_field:
                raise ConfigError(
                    "La sincronización incremental necesita un campo cursor", details={"field": "cursor_field"}
                )
            if cursor_field not in col_types:
                raise ConfigError(f"El campo cursor «{cursor_field}» no existe en la tabla")
            if cursor_field not in names:
                names.append(cursor_field)
                columns.append(next(c for c in table["columns"] if c["name"] == cursor_field))
            key_columns = [cursor_field, *[k for k in primary_key if k != cursor_field]]
            lower_bound: Any = request.cursor
        else:
            cursor_field = None
            key_columns = primary_key
            lower_bound = None
        key_types = [col_types[k] for k in key_columns]

        target = kb_identifier(str(request.options.get("target_table") or name))
        kb_columns = [
            ColumnDef(
                name=c["name"],
                type=c["kb_type"],
                nullable=bool(c["nullable"]) and c["name"] not in primary_key,
                comment=c.get("comment"),
            )
            for c in columns
        ]
        after: list[Any] | None = None
        total = 0
        batches = 0
        last_cursor: Any = request.cursor
        batch_size = max(50, min(int(request.batch_size), 5000))
        while True:
            try:
                page = await eng.fetch_batch(
                    schema=schema,
                    table=table["name"],
                    columns=names,
                    key_columns=key_columns,
                    key_types=key_types,
                    after=after,
                    lower_bound=lower_bound,
                    limit=batch_size,
                )
            except SqlError as exc:
                raise _db_error(exc) from exc
            rows = page["rows"]
            if not rows:
                break
            batches += 1
            total += len(rows)
            await sink.rows(target, kb_columns, [V.revive_row(col_types, r) for r in rows], primary_key)
            after = page["last_key"]
            if cursor_field is not None and after:
                last_cursor = after[0]
            if len(rows) < batch_size:
                break
        return SyncOutcome(
            next_cursor=None if last_cursor is None else str(last_cursor),
            stats={"rows": total, "batches": batches, "table": target, "source": f"{schema}.{table['name']}"},
        )


_DB_FIELDS = [
    ConfigField(key="connection_string", kind="secret", required=True, secret=True),
    ConfigField(key="read_only", kind="boolean", default=True),
    ConfigField(key="schemas", kind="list"),
]


@register
class PostgresAdapter(DatabaseAdapter):
    dialect = "postgresql"
    spec = ConnectorSpec(
        key="postgresql",
        name="PostgreSQL",
        category="database",
        auth_type="connection_string",
        description="Consultas de solo lectura, introspección del esquema y sincronización de tablas.",
        description_en="Read-only queries, schema introspection and table syncs.",
        icon="database",
        capabilities=Capabilities(
            actions=["query", "list_tables", "describe_table"],
            sync=True,
            sync_resources=["table"],
            introspection=True,
            agent=True,
        ),
        config_fields=[
            ConfigField(
                key="connection_string",
                kind="secret",
                required=True,
                secret=True,
                placeholder="postgresql://usuario:contraseña@servidor:5432/base",
            ),
            *_DB_FIELDS[1:],
        ],
        docs_url="https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNSTRING",
    )


@register
class MySqlAdapter(DatabaseAdapter):
    dialect = "mysql"
    spec = ConnectorSpec(
        key="mysql",
        name="MySQL",
        category="database",
        auth_type="connection_string",
        description="MySQL y MariaDB: consultas de solo lectura, introspección y sincronización de tablas.",
        description_en="MySQL and MariaDB: read-only queries, introspection and table syncs.",
        icon="database",
        capabilities=Capabilities(
            actions=["query", "list_tables", "describe_table"],
            sync=True,
            sync_resources=["table"],
            introspection=True,
            agent=True,
        ),
        config_fields=[
            ConfigField(
                key="connection_string",
                kind="secret",
                required=True,
                secret=True,
                placeholder="mysql://usuario:contraseña@servidor:3306/base?ssl=true",
            ),
            *_DB_FIELDS[1:],
        ],
    )


@register
class SqlServerAdapter(DatabaseAdapter):
    dialect = "sqlserver"
    spec = ConnectorSpec(
        key="sqlserver",
        name="SQL Server",
        category="database",
        auth_type="connection_string",
        description="Microsoft SQL Server y Azure SQL: consultas de solo lectura, introspección y sincronización.",
        description_en="Microsoft SQL Server and Azure SQL: read-only queries, introspection and syncs.",
        icon="database",
        capabilities=Capabilities(
            actions=["query", "list_tables", "describe_table"],
            sync=True,
            sync_resources=["table"],
            introspection=True,
            agent=True,
        ),
        config_fields=[
            ConfigField(
                key="connection_string",
                kind="secret",
                required=True,
                secret=True,
                placeholder="Server=tcp:servidor,1433;Database=base;User ID=usuario;Password=…;Encrypt=True",
            ),
            *_DB_FIELDS[1:],
        ],
    )
