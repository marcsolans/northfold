"""Demo connections (no OAuth app configured): every OAuth connector produces realistic data end to end."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from messer_connectors import registry
from messer_connectors.adapters.salesforce import soql_datetime
from messer_connectors.base import ColumnDef, ConnectionContext, SyncFile, SyncRequest
from messer_connectors.util import to_rfc3339

OAUTH_KEYS = [s.key for s in registry.catalog() if s.auth_type == "oauth2"]
EPOCH = datetime.now(UTC) - timedelta(hours=10)


def demo_ctx(key: str) -> ConnectionContext:
    extra: dict[str, Any] = {}
    if key == "salesforce":
        from messer_connectors.demo import fixture

        extra = {"instance_url": fixture("salesforce")["org"]["instance_url"]}
    return ConnectionContext(
        connection_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        credentials={"access_token": "demo", "extra": extra},
        config={"demo_epoch": EPOCH.isoformat()},
        demo=True,
        connector_key=key,
    )


class RecordingSink:
    def __init__(self) -> None:
        self.files: list[SyncFile] = []
        self.tables: dict[str, list[dict[str, Any]]] = {}
        self.columns: dict[str, list[ColumnDef]] = {}

    async def should_skip(self, external_id: str, version: str | None) -> bool:
        return False

    async def file(self, item: SyncFile) -> None:
        self.files.append(item)

    async def rows(
        self, table: str, columns: list[ColumnDef], rows: list[dict[str, Any]], primary_key: list[str]
    ) -> None:
        self.tables.setdefault(table, []).extend(rows)
        self.columns[table] = columns


def test_every_oauth_connector_supports_demo() -> None:
    assert set(OAUTH_KEYS) == {
        "google_drive", "gmail", "google_calendar", "onedrive", "sharepoint", "outlook", "slack", "notion", "hubspot",
        "salesforce",
    }  # fmt: skip
    for key in OAUTH_KEYS:
        spec = registry.get_adapter(key).spec
        assert spec.capabilities.demo and spec.oauth is not None


READ_ACTIONS: list[tuple[str, str, dict[str, Any]]] = [
    ("google_drive", "list_folders", {}),
    ("google_drive", "list_files", {"folder_id": "fld-policies"}),
    ("google_drive", "search_files", {"query": "devoluciones"}),
    ("google_drive", "get_file", {"file_id": "doc-returns"}),
    ("gmail", "search_messages", {"query": "factura"}),
    ("gmail", "get_message", {"message_id": "msg-0001"}),
    ("google_calendar", "list_calendars", {}),
    (
        "google_calendar",
        "list_events",
        {"time_min": to_rfc3339(EPOCH), "time_max": to_rfc3339(EPOCH + timedelta(days=10))},
    ),
    ("onedrive", "list_folder", {}),
    ("onedrive", "search_files", {"query": "tarifa"}),
    ("onedrive", "get_file", {"item_id": "od-faq"}),
    ("sharepoint", "list_sites", {}),
    ("sharepoint", "list_drives", {"site_id": "site-intranet"}),
    ("sharepoint", "list_folder", {"drive_id": "drv-intranet", "item_id": "sp-proc"}),
    ("outlook", "search_messages", {"query": "factura"}),
    ("outlook", "get_message", {"message_id": "olk-0002"}),
    ("outlook", "list_events", {"start": to_rfc3339(EPOCH), "end": to_rfc3339(EPOCH + timedelta(days=10))}),
    ("slack", "list_channels", {}),
    ("slack", "channel_history", {"channel": "C0FACTURAS"}),
    ("slack", "search_messages", {"query": "abono"}),
    ("notion", "search", {"query": "facturación"}),
    ("notion", "get_page", {"page_id": "pg-billing"}),
    ("notion", "query_database", {"database_id": "db-incidents"}),
    ("hubspot", "search_records", {"object": "contacts", "query": "Mendaro"}),
    ("hubspot", "get_record", {"object": "deals", "id": "7002"}),
    ("salesforce", "soql_query", {"query": "SELECT Id, Name, Industry FROM Account WHERE BillingCity = 'Bilbao'"}),
    ("salesforce", "get_record", {"object": "Contact", "id": "003000000000001AAA"}),
]


@pytest.mark.parametrize(("key", "action", "args"), READ_ACTIONS, ids=[f"{k}.{a}" for k, a, _ in READ_ACTIONS])
async def test_demo_read_actions_return_data(key: str, action: str, args: dict[str, Any]) -> None:
    adapter = registry.get_adapter(key)
    assert not adapter.action(action).side_effect
    result = await adapter.run_action(demo_ctx(key), action, args)
    assert result, f"{key}.{action} returned nothing"
    if isinstance(result, dict) and "results" in result:
        assert result["results"]
    if isinstance(result, dict) and "records" in result:
        assert result["records"]


async def test_demo_content_is_realistic() -> None:
    drive = await registry.get_adapter("google_drive").run_action(
        demo_ctx("google_drive"), "get_file", {"file_id": "doc-returns"}
    )
    assert "500 €" in drive["content"] and drive["exported_as"] == "text/markdown"
    mail = await registry.get_adapter("gmail").run_action(demo_ctx("gmail"), "get_message", {"message_id": "msg-0004"})
    assert "F-2026-0488" in mail["body"] and mail["from"].startswith("Ane Ugalde")
    page = await registry.get_adapter("notion").run_action(demo_ctx("notion"), "get_page", {"page_id": "pg-billing"})
    assert page["content"].startswith("# Proceso de facturación") and "## Abonos" in page["content"]
    sf = await registry.get_adapter("salesforce").run_action(
        demo_ctx("salesforce"), "soql_query", {"query": "SELECT Id, Name FROM Account WHERE BillingCity = 'Bilbao'"}
    )
    assert [r["Name"] for r in sf["records"]] == ["Construcciones Ugalde S.L."]


SIDE_EFFECTS: list[tuple[str, str, dict[str, Any]]] = [
    ("gmail", "create_draft", {"to": ["cliente@example.com"], "subject": "Duplicado", "body": "Adjunto la factura."}),
    ("gmail", "send_message", {"to": ["cliente@example.com"], "subject": "Duplicado", "body": "Adjunto la factura."}),
    (
        "google_calendar",
        "create_event",
        {"summary": "Llamada", "start": "2026-11-02T10:00:00+01:00", "end": "2026-11-02T10:30:00+01:00"},
    ),
    ("outlook", "send_mail", {"to": ["cliente@example.com"], "subject": "Hola", "body": "Texto"}),
    ("outlook", "create_event", {"subject": "Visita", "start": "2026-11-03T09:00:00", "end": "2026-11-03T10:00:00"}),
    ("slack", "post_message", {"channel": "C0SOPORTE", "text": "Incidencia resuelta"}),
    (
        "hubspot",
        "create_record",
        {"object": "contacts", "properties": {"email": "nuevo@example.com", "firstname": "Ana"}},
    ),
    (
        "hubspot",
        "update_record",
        {"object": "contacts", "id": "501", "properties": {"jobtitle": "Director de compras"}},
    ),
    ("salesforce", "create_record", {"object": "Lead", "fields": {"LastName": "Nuevo", "Company": "Acme"}}),
    ("salesforce", "update_record", {"object": "Lead", "id": "00Q000000000001AAA", "fields": {"Status": "Closed"}}),
]


@pytest.mark.parametrize(("key", "action", "args"), SIDE_EFFECTS, ids=[f"{k}.{a}" for k, a, _ in SIDE_EFFECTS])
async def test_demo_side_effect_actions(key: str, action: str, args: dict[str, Any]) -> None:
    adapter = registry.get_adapter(key)
    assert adapter.action(action).side_effect  # approval required by default
    result = await adapter.run_action(demo_ctx(key), action, args)
    assert result


SYNCS: list[tuple[str, str, str]] = [
    ("google_drive", "folder:fld-albor", "files"),
    ("onedrive", "folder:me:root", "files"),
    ("sharepoint", "folder:drv-finance:root", "files"),
    ("notion", "all", "files"),
    ("notion", "database:db-incidents", "files"),
    ("hubspot", "object:contacts", "table"),
    ("hubspot", "object:deals", "table"),
    ("salesforce", "object:Account", "table"),
]


@pytest.mark.parametrize(("key", "resource", "kind"), SYNCS, ids=[f"{k}:{r}" for k, r, _ in SYNCS])
async def test_demo_syncs_produce_data(key: str, resource: str, kind: str) -> None:
    sink = RecordingSink()
    outcome = await registry.get_adapter(key).sync(demo_ctx(key), SyncRequest(resource=resource), sink)
    if kind == "files":
        assert sink.files and all(f.data for f in sink.files)
        assert len({f.external_id for f in sink.files}) == len(sink.files)
    else:
        assert sink.tables
        table, rows = next(iter(sink.tables.items()))
        assert rows and all(r.get("id") for r in rows)
        assert any(c.type == "timestamp" for c in sink.columns[table])
    assert outcome.next_cursor


async def test_drive_sync_recurses_and_exports() -> None:
    sink = RecordingSink()
    await registry.get_adapter("google_drive").sync(
        demo_ctx("google_drive"), SyncRequest(resource="folder:fld-albor"), sink
    )
    paths = {f.path for f in sink.files}
    assert "Condiciones y políticas/Política de devoluciones y abonos.md" in paths
    assert "Facturación/Facturas pendientes.csv" in paths
    sheet = next(f for f in sink.files if f.filename == "Tarifa 2026.csv")
    assert sheet.mime == "text/csv" and sheet.data.startswith(b"referencia,producto")


async def test_incremental_sync_uses_cursor() -> None:
    adapter = registry.get_adapter("hubspot")
    full = RecordingSink()
    outcome = await adapter.sync(demo_ctx("hubspot"), SyncRequest(resource="object:contacts"), full)
    incremental = RecordingSink()
    later = await adapter.sync(
        demo_ctx("hubspot"),
        SyncRequest(resource="object:contacts", mode="incremental", cursor=outcome.next_cursor),
        incremental,
    )
    total_full = len(full.tables["hubspot_contacts"])
    total_inc = sum(len(r) for r in incremental.tables.values())
    assert 0 < total_inc < total_full  # only the most recently modified record(s)
    assert later.next_cursor == outcome.next_cursor


EVENTS: list[tuple[str, str, str]] = [
    ("gmail", "new_email", str(int(EPOCH.timestamp() * 1000))),
    ("outlook", "new_email", to_rfc3339(EPOCH)),
    ("hubspot", "new_contact", str(int(EPOCH.timestamp() * 1000))),
    ("salesforce", "new_record", soql_datetime(EPOCH)),
    ("google_drive", "new_file", to_rfc3339(EPOCH)),
]


@pytest.mark.parametrize(("key", "event", "cursor"), EVENTS, ids=[f"{k}.{e}" for k, e, _ in EVENTS])
async def test_demo_events(key: str, event: str, cursor: str) -> None:
    adapter = registry.get_adapter(key)
    ctx = demo_ctx(key)
    events, baseline = await adapter.poll_events(ctx, event, None)
    assert events == [] and baseline  # no backfill on the first poll
    events, next_cursor = await adapter.poll_events(ctx, event, cursor)
    assert len(events) >= 4  # incoming demo items arrive every 2 hours after the epoch
    assert all(e["event"] == event and e["id"] and e["data"] for e in events)
    assert next_cursor and next_cursor != cursor
    again, _ = await adapter.poll_events(ctx, event, next_cursor)
    assert again == []
