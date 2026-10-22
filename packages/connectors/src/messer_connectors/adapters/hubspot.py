"""HubSpot CRM: contacts, companies and deals (search, create, update), syncs to knowledge tables, events."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from ..base import (
    ActionSpec,
    Capabilities,
    ColumnDef,
    ConfigError,
    ConnectionContext,
    ConnectorSpec,
    KbColumnType,
    OAuthSpec,
    Resource,
    SyncOutcome,
    SyncRequest,
    SyncSink,
    obj_schema,
)
from ..demo import saas as demo_saas
from ..registry import register
from ..sql import values as V
from ..util import kb_identifier, validate_args
from ._oauth import ApiSession, OAuthAdapter

OBJECTS: dict[str, dict[str, Any]] = {
    "contacts": {
        "label": "Contactos",
        "modified": "lastmodifieddate",
        "properties": [
            "firstname",
            "lastname",
            "email",
            "phone",
            "company",
            "jobtitle",
            "lifecyclestage",
            "city",
            "createdate",
            "lastmodifieddate",
        ],
    },
    "companies": {
        "label": "Empresas",
        "modified": "hs_lastmodifieddate",
        "properties": [
            "name",
            "domain",
            "industry",
            "city",
            "country",
            "numberofemployees",
            "annualrevenue",
            "createdate",
            "hs_lastmodifieddate",
        ],
    },
    "deals": {
        "label": "Negocios",
        "modified": "hs_lastmodifieddate",
        "properties": ["dealname", "amount", "dealstage", "pipeline", "closedate", "createdate", "hs_lastmodifieddate"],
    },
}
PROPERTY_TYPES: dict[str, KbColumnType] = {
    "amount": "numeric",
    "annualrevenue": "numeric",
    "numberofemployees": "integer",
    "createdate": "timestamp",
    "lastmodifieddate": "timestamp",
    "hs_lastmodifieddate": "timestamp",
    "closedate": "timestamp",
}
OBJECT_ENUM = sorted(OBJECTS)


def _ms(value: str | None) -> int:
    if not value:
        return 0
    if value.isdigit():
        return int(value)
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def _record_out(rec: dict[str, Any]) -> dict[str, Any]:
    return {"id": rec.get("id"), **(rec.get("properties") or {}), "archived": rec.get("archived", False)}


@register
class HubSpotAdapter(OAuthAdapter):
    api_base = "https://api.hubapi.com"
    demo_handler = staticmethod(demo_saas.hubspot_handler)  # type: ignore[assignment]
    spec = ConnectorSpec(
        key="hubspot",
        name="HubSpot",
        category="crm",
        auth_type="oauth2",
        description="Contactos, empresas y negocios de HubSpot: busca, crea, actualiza y sincroniza con tablas.",
        description_en="HubSpot contacts, companies and deals: search, create, update and sync to tables.",
        icon="hubspot",
        oauth=OAuthSpec(
            provider="hubspot",
            authorize_url="https://app.hubspot.com/oauth/authorize",
            token_url="https://api.hubapi.com/oauth/v1/token",
            scopes=[
                "oauth",
                "crm.objects.contacts.read",
                "crm.objects.contacts.write",
                "crm.objects.companies.read",
                "crm.objects.companies.write",
                "crm.objects.deals.read",
                "crm.objects.deals.write",
            ],
            client_id_setting="hubspot_client_id",
            client_secret_setting="hubspot_client_secret",
        ),
        capabilities=Capabilities(
            actions=["search_records", "get_record", "create_record", "update_record"],
            sync=True,
            sync_resources=["object"],
            events=["new_contact"],
            demo=True,
        ),
        docs_url="https://developers.hubspot.com/docs/api/crm/understanding-the-crm",
    )

    def actions(self) -> list[ActionSpec]:
        obj = {"type": "string", "enum": OBJECT_ENUM, "default": "contacts"}
        return [
            ActionSpec(
                name="search_records",
                title="Buscar registros",
                description="Busca contactos, empresas o negocios por texto.",
                input_schema=obj_schema(
                    {
                        "object": obj,
                        "query": {"type": "string", "default": ""},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
                        "properties": {"type": "array", "items": {"type": "string"}},
                    }
                ),
            ),
            ActionSpec(
                name="get_record",
                title="Leer registro",
                description="Un registro por su ID.",
                input_schema=obj_schema({"object": obj, "id": {"type": "string", "minLength": 1}}, ["id"]),
            ),
            ActionSpec(
                name="create_record",
                title="Crear registro",
                description="Crea un contacto, empresa o negocio con las propiedades indicadas.",
                input_schema=obj_schema(
                    {"object": obj, "properties": {"type": "object", "minProperties": 1}}, ["properties"]
                ),
                side_effect=True,
            ),
            ActionSpec(
                name="update_record",
                title="Actualizar registro",
                description="Actualiza propiedades de un registro.",
                input_schema=obj_schema(
                    {
                        "object": obj,
                        "id": {"type": "string", "minLength": 1},
                        "properties": {"type": "object", "minProperties": 1},
                    },
                    ["id", "properties"],
                ),
                side_effect=True,
            ),
        ]

    async def whoami(self, ctx: ConnectionContext) -> dict[str, Any]:
        async with self.session(ctx) as api:
            info = await api.get("/account-info/v3/details")
        return {"account": f"HubSpot {info.get('portalId')}", "region": info.get("dataHostingLocation")}

    async def run_action(self, ctx: ConnectionContext, action: str, args: dict[str, Any]) -> Any:
        data = validate_args(self.action(action), args)
        obj = str(data.get("object") or "contacts")
        props = data.get("properties") if action == "search_records" else None
        async with self.session(ctx) as api:
            if action == "search_records":
                body: dict[str, Any] = {
                    "limit": int(data["limit"]),
                    "properties": props or OBJECTS[obj]["properties"],
                    "sorts": [{"propertyName": OBJECTS[obj]["modified"], "direction": "DESCENDING"}],
                }
                if data["query"]:
                    body["query"] = data["query"]
                res = await api.post(f"/crm/v3/objects/{obj}/search", json=body)
                return {"total": res.get("total", 0), "results": [_record_out(r) for r in res.get("results", [])]}
            if action == "get_record":
                res = await api.get(
                    f"/crm/v3/objects/{obj}/{data['id']}", params={"properties": ",".join(OBJECTS[obj]["properties"])}
                )
                return _record_out(res)
            if action == "create_record":
                res = await api.post(f"/crm/v3/objects/{obj}", json={"properties": data["properties"]})
                return _record_out(res)
            if action == "update_record":
                res = await api.call(
                    "PATCH", f"/crm/v3/objects/{obj}/{data['id']}", json={"properties": data["properties"]}
                )
                return _record_out(res)
        return await super().run_action(ctx, action, args)

    async def list_resources(self, ctx: ConnectionContext, parent: str | None = None) -> list[Resource]:
        return [
            Resource(
                id=f"object:{key}",
                name=meta["label"],
                kind="object",
                meta={"primary_key": ["id"], "cursor_field": meta["modified"]},
            )
            for key, meta in OBJECTS.items()
        ]

    async def _search_all(
        self, api: ApiSession, obj: str, body: dict[str, Any], cap: int = 10_000
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        after: str | None = None
        while len(out) < cap:
            page_body = {**body, "limit": 100}
            if after:
                page_body["after"] = after
            res = await api.post(f"/crm/v3/objects/{obj}/search", json=page_body)
            out.extend(res.get("results", []))
            after = ((res.get("paging") or {}).get("next") or {}).get("after")
            if not after:
                break
        return out

    async def sync(self, ctx: ConnectionContext, request: SyncRequest, sink: SyncSink) -> SyncOutcome:
        obj = request.resource.removeprefix("object:")
        if obj not in OBJECTS:
            raise ConfigError(f"Objeto de HubSpot no admitido: {obj}", details={"supported": OBJECT_ENUM})
        meta = OBJECTS[obj]
        extra = [str(p) for p in request.options.get("properties") or [] if str(p) not in meta["properties"]]
        properties = [*meta["properties"], *extra]
        table = kb_identifier(str(request.options.get("target_table") or f"hubspot_{obj}"))
        columns = [ColumnDef(name="id", type="text", nullable=False, comment=f"ID de HubSpot ({obj})")]
        columns += [ColumnDef(name=kb_identifier(p), type=PROPERTY_TYPES.get(p, "text")) for p in properties]
        types = {c.name: c.type for c in columns}
        modified = meta["modified"]
        since_ms = _ms(request.cursor) if request.mode == "incremental" and request.cursor else None
        newest = since_ms or 0
        total = 0
        batches = 0

        def to_row(rec: dict[str, Any]) -> dict[str, Any]:
            props = rec.get("properties") or {}
            row: dict[str, Any] = {"id": str(rec.get("id"))}
            for p in properties:
                row[kb_identifier(p)] = props.get(p)
            return V.revive_row(types, row)

        async with self.session(ctx) as api:
            if since_ms is not None:
                body = {
                    "filterGroups": [
                        {"filters": [{"propertyName": modified, "operator": "GTE", "value": str(since_ms)}]}
                    ],
                    "sorts": [{"propertyName": modified, "direction": "ASCENDING"}],
                    "properties": properties,
                }
                records = await self._search_all(api, obj, body)
                for start in range(0, len(records), request.batch_size):
                    chunk = records[start : start + request.batch_size]
                    await sink.rows(table, columns, [to_row(r) for r in chunk], ["id"])
                    batches += 1
                    total += len(chunk)
                    newest = max([newest, *(_ms((r.get("properties") or {}).get(modified)) for r in chunk)])
            else:
                after: str | None = None
                while True:
                    params: dict[str, Any] = {"limit": 100, "properties": ",".join(properties), "archived": "false"}
                    if after:
                        params["after"] = after
                    res = await api.get(f"/crm/v3/objects/{obj}", params=params)
                    records = res.get("results", [])
                    if records:
                        await sink.rows(table, columns, [to_row(r) for r in records], ["id"])
                        batches += 1
                        total += len(records)
                        newest = max([newest, *(_ms((r.get("properties") or {}).get(modified)) for r in records)])
                    after = ((res.get("paging") or {}).get("next") or {}).get("after")
                    if not after:
                        break
        return SyncOutcome(
            next_cursor=str(newest) if newest else request.cursor,
            stats={"rows": total, "batches": batches, "table": table, "object": obj},
        )

    async def poll_events(
        self, ctx: ConnectionContext, event: str, cursor: str | None
    ) -> tuple[list[dict[str, Any]], str | None]:
        self._check_event(event)
        if cursor is None:
            return [], str(int(time.time() * 1000))
        body = {
            "filterGroups": [{"filters": [{"propertyName": "createdate", "operator": "GT", "value": cursor}]}],
            "sorts": [{"propertyName": "createdate", "direction": "ASCENDING"}],
            "properties": OBJECTS["contacts"]["properties"],
            "limit": 100,
        }
        async with self.session(ctx) as api:
            res = await api.post("/crm/v3/objects/contacts/search", json=body)
        records = res.get("results", [])
        events = [
            {
                "id": str(r.get("id")),
                "event": "new_contact",
                "occurred_at": (r.get("properties") or {}).get("createdate"),
                "data": _record_out(r),
            }
            for r in records
        ]
        newest = max([int(cursor), *(_ms((r.get("properties") or {}).get("createdate")) for r in records)])
        return events, str(newest)
