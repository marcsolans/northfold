"""Salesforce: SOQL queries, create/update records, object syncs to knowledge tables and new-record events."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from ..base import (
    ActionSpec,
    Capabilities,
    ColumnDef,
    ConfigError,
    ConnectionContext,
    ConnectorAuthError,
    ConnectorError,
    ConnectorSpec,
    KbColumnType,
    OAuthSpec,
    Resource,
    SyncOutcome,
    SyncRequest,
    SyncSink,
    obj_schema,
)
from ..demo import fixture
from ..demo import saas as demo_saas
from ..registry import register
from ..sql import values as V
from ..util import kb_identifier, validate_args
from ._oauth import ApiSession, OAuthAdapter

API_VERSION = "v61.0"
STAMP = ("CreatedDate", "LastModifiedDate", "SystemModstamp")
DEFAULT_FIELDS: dict[str, list[str]] = {
    "Account": [
        "Id",
        "Name",
        "Industry",
        "Type",
        "BillingCity",
        "BillingCountry",
        "Phone",
        "Website",
        "AnnualRevenue",
        "NumberOfEmployees",
        *STAMP,
    ],
    "Contact": ["Id", "FirstName", "LastName", "Email", "Phone", "Title", "AccountId", *STAMP],
    "Opportunity": ["Id", "Name", "AccountId", "StageName", "Amount", "CloseDate", "Probability", *STAMP],
    "Lead": ["Id", "FirstName", "LastName", "Company", "Email", "Status", "LeadSource", *STAMP],
    "Case": ["Id", "CaseNumber", "Subject", "Status", "Priority", "Origin", "AccountId", "ContactId", *STAMP],
}
OBJECT_LABELS = {
    "Account": "Cuentas",
    "Contact": "Contactos",
    "Opportunity": "Oportunidades",
    "Lead": "Leads",
    "Case": "Casos",
}
SF_TYPES: dict[str, KbColumnType] = {
    "double": "numeric",
    "currency": "numeric",
    "percent": "numeric",
    "int": "integer",
    "long": "integer",
    "boolean": "boolean",
    "date": "date",
    "datetime": "timestamp",
}
_IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def soql_datetime(value: str | datetime) -> str:
    """Normalize to the SOQL dateTime literal ``YYYY-MM-DDThh:mm:ssZ``."""
    if isinstance(value, str):
        text = value.strip().replace("+0000", "+00:00").replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    else:
        parsed = value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _check_ident(value: str, what: str) -> str:
    if not _IDENT.match(value):
        raise ConfigError(f"{what} no válido: {value}")
    return value


def _clean(record: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if k != "attributes"}


@register
class SalesforceAdapter(OAuthAdapter):
    demo_handler = staticmethod(demo_saas.salesforce_handler)  # type: ignore[assignment]
    spec = ConnectorSpec(
        key="salesforce",
        name="Salesforce",
        category="crm",
        auth_type="oauth2",
        description="Consultas SOQL, alta y actualización de registros y sincronización de objetos con tablas.",
        description_en="SOQL queries, record creation and updates, and object syncs to tables.",
        icon="salesforce",
        oauth=OAuthSpec(
            provider="salesforce",
            authorize_url="https://login.salesforce.com/services/oauth2/authorize",
            token_url="https://login.salesforce.com/services/oauth2/token",
            scopes=["api", "refresh_token", "offline_access"],
            client_id_setting="salesforce_client_id",
            client_secret_setting="salesforce_client_secret",
            pkce=True,
            extra_authorize_params={"prompt": "login consent"},
        ),
        capabilities=Capabilities(
            actions=["soql_query", "get_record", "create_record", "update_record"],
            sync=True,
            sync_resources=["object"],
            events=["new_record"],
            demo=True,
        ),
        docs_url="https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/",
    )

    def base_url(self, ctx: ConnectionContext) -> str:
        instance = (ctx.credentials.get("extra") or {}).get("instance_url")
        if not instance:
            if ctx.demo:
                return str(fixture("salesforce")["org"]["instance_url"])
            raise ConnectorAuthError("Falta la URL de instancia de Salesforce. Vuelve a conectar la cuenta.")
        return str(instance).rstrip("/")

    def actions(self) -> list[ActionSpec]:
        obj = {"type": "string", "minLength": 1, "pattern": "^[A-Za-z][A-Za-z0-9_]*$"}
        return [
            ActionSpec(
                name="soql_query",
                title="Consulta SOQL",
                description="Ejecuta una consulta SOQL (SELECT … FROM …) y devuelve los registros.",
                input_schema=obj_schema(
                    {
                        "query": {"type": "string", "minLength": 1},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 2000, "default": 200},
                    },
                    ["query"],
                ),
            ),
            ActionSpec(
                name="get_record",
                title="Leer registro",
                description="Un registro por objeto e ID.",
                input_schema=obj_schema({"object": obj, "id": {"type": "string", "minLength": 15}}, ["object", "id"]),
            ),
            ActionSpec(
                name="create_record",
                title="Crear registro",
                description="Crea un registro (Lead, Contact, Opportunity…) con los campos indicados.",
                input_schema=obj_schema(
                    {"object": obj, "fields": {"type": "object", "minProperties": 1}}, ["object", "fields"]
                ),
                side_effect=True,
            ),
            ActionSpec(
                name="update_record",
                title="Actualizar registro",
                description="Actualiza campos de un registro.",
                input_schema=obj_schema(
                    {
                        "object": obj,
                        "id": {"type": "string", "minLength": 15},
                        "fields": {"type": "object", "minProperties": 1},
                    },
                    ["object", "id", "fields"],
                ),
                side_effect=True,
            ),
        ]

    async def whoami(self, ctx: ConnectionContext) -> dict[str, Any]:
        async with self.session(ctx) as api:
            info = await api.get("/services/oauth2/userinfo")
        return {"email": info.get("preferred_username") or info.get("email"), "account": info.get("organization_id")}

    async def _query(self, api: ApiSession, soql: str, limit: int) -> tuple[list[dict[str, Any]], int]:
        res = await api.get(f"/services/data/{API_VERSION}/query", params={"q": soql})
        records = list(res.get("records", []))
        total = int(res.get("totalSize") or len(records))
        while not res.get("done", True) and res.get("nextRecordsUrl") and len(records) < limit:
            res = await api.get(str(res["nextRecordsUrl"]))
            records.extend(res.get("records", []))
        return records[:limit], total

    async def run_action(self, ctx: ConnectionContext, action: str, args: dict[str, Any]) -> Any:
        data = validate_args(self.action(action), args)
        async with self.session(ctx) as api:
            if action == "soql_query":
                soql = str(data["query"]).strip().rstrip(";")
                if not soql.lower().startswith("select "):
                    raise ConnectorError("Solo se admiten consultas SOQL SELECT", code="invalid_soql")
                records, total = await self._query(api, soql, int(data["limit"]))
                return {"total": total, "records": [_clean(r) for r in records]}
            obj = _check_ident(str(data["object"]), "Objeto")
            base = f"/services/data/{API_VERSION}/sobjects/{obj}"
            if action == "get_record":
                return _clean(await api.get(f"{base}/{data['id']}"))
            if action == "create_record":
                res = await api.post(base, json=data["fields"])
                return {"id": res.get("id"), "success": res.get("success", True), "object": obj}
            if action == "update_record":
                await api.call("PATCH", f"{base}/{data['id']}", json=data["fields"])
                return {"id": data["id"], "success": True, "object": obj}
        return await super().run_action(ctx, action, args)

    async def list_resources(self, ctx: ConnectionContext, parent: str | None = None) -> list[Resource]:
        return [
            Resource(
                id=f"object:{name}",
                name=f"{label} ({name})",
                kind="object",
                meta={"primary_key": ["Id"], "cursor_field": "SystemModstamp"},
            )
            for name, label in OBJECT_LABELS.items()
        ]

    async def _describe(self, api: ApiSession, obj: str) -> dict[str, str]:
        res = await api.get(f"/services/data/{API_VERSION}/sobjects/{obj}/describe")
        return {str(f["name"]): str(f.get("type") or "string") for f in res.get("fields", [])}

    async def sync(self, ctx: ConnectionContext, request: SyncRequest, sink: SyncSink) -> SyncOutcome:
        obj = _check_ident(request.resource.removeprefix("object:"), "Objeto")
        wanted = [str(f) for f in request.options.get("fields") or DEFAULT_FIELDS.get(obj, [])]
        if not wanted:
            raise ConfigError("Indica los campos a sincronizar para este objeto", details={"field": "fields"})
        async with self.session(ctx) as api:
            described = await self._describe(api, obj)
            fields = [f for f in dict.fromkeys(["Id", *wanted, "SystemModstamp"]) if f in described]
            if "Id" not in fields:
                raise ConfigError(f"El objeto {obj} no es accesible")
            columns = [
                ColumnDef(name=kb_identifier(f), type=SF_TYPES.get(described[f].lower(), "text"), nullable=f != "Id")
                for f in fields
            ]
            types = {c.name: c.type for c in columns}
            table = kb_identifier(str(request.options.get("target_table") or f"salesforce_{obj.lower()}"))
            soql = f"SELECT {', '.join(fields)} FROM {obj}"
            if request.mode == "incremental" and request.cursor:
                soql += f" WHERE SystemModstamp >= {soql_datetime(request.cursor)}"
            soql += " ORDER BY SystemModstamp ASC"
            total = 0
            batches = 0
            newest = request.cursor
            res = await api.get(f"/services/data/{API_VERSION}/query", params={"q": soql})
            while True:
                records = res.get("records", [])
                if records:
                    rows = [V.revive_row(types, {kb_identifier(f): r.get(f) for f in fields}) for r in records]
                    await sink.rows(table, columns, rows, ["id"])
                    batches += 1
                    total += len(records)
                    stamps = [str(r.get("SystemModstamp")) for r in records if r.get("SystemModstamp")]
                    if stamps:
                        newest = max([soql_datetime(s) for s in stamps] + ([soql_datetime(newest)] if newest else []))
                if res.get("done", True) or not res.get("nextRecordsUrl"):
                    break
                res = await api.get(str(res["nextRecordsUrl"]))
        return SyncOutcome(next_cursor=newest, stats={"rows": total, "batches": batches, "table": table, "object": obj})

    async def poll_events(
        self, ctx: ConnectionContext, event: str, cursor: str | None
    ) -> tuple[list[dict[str, Any]], str | None]:
        self._check_event(event)
        obj = _check_ident(
            event.split(":", 1)[1] if ":" in event else str(ctx.config.get("event_object") or "Lead"), "Objeto"
        )
        if cursor is None:
            return [], soql_datetime(datetime.now(UTC))
        fields = [
            f for f in DEFAULT_FIELDS.get(obj, ["Id", "CreatedDate"]) if f not in ("LastModifiedDate", "SystemModstamp")
        ]
        if "CreatedDate" not in fields:
            fields.append("CreatedDate")
        soql = f"SELECT {', '.join(fields)} FROM {obj} WHERE CreatedDate > {soql_datetime(cursor)} ORDER BY CreatedDate ASC LIMIT 200"
        async with self.session(ctx) as api:
            records, _ = await self._query(api, soql, 200)
        events = [
            {
                "id": r.get("Id"),
                "event": "new_record",
                "occurred_at": r.get("CreatedDate"),
                "data": {"object": obj, **_clean(r)},
            }
            for r in records
        ]
        stamps = [soql_datetime(str(r["CreatedDate"])) for r in records if r.get("CreatedDate")]
        return events, max([cursor, *stamps]) if stamps else cursor
