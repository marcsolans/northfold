"""Phase 4 criterion: sync a Google Drive folder (its demo, without an OAuth app) into a knowledge base."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import timedelta

import pytest
from sqlalchemy import select

from messer_api.services.connector_syncs import enqueue_due_syncs, execute_sync
from messer_api.services.knowledge import create_kb
from messer_common.db import system_session
from messer_common.db.models import KbFile, Sync
from messer_common.settings import reset_settings_cache
from messer_common.testing.fixtures import principal_for


@pytest.fixture
def no_google_app(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "")
    reset_settings_cache()
    yield
    reset_settings_cache()


async def _files(kb_id: uuid.UUID) -> list[KbFile]:
    async with system_session() as s:
        return list((await s.execute(select(KbFile).where(KbFile.kb_id == kb_id).order_by(KbFile.filename))).scalars())


async def test_sync_drive_folder_demo_into_knowledge_base(make_org, login, no_google_app) -> None:  # type: ignore[no-untyped-def]
    org, user = await make_org()
    client = await login(user.email)
    kb = await create_kb(principal_for(user.id, org.id, "owner"), name="Políticas")

    started = (await client.post("/api/v1/connections/oauth/google_drive/start", json={})).json()
    assert started["mode"] == "demo"
    conn = started["connection"]

    roots = (await client.get(f"/api/v1/connections/{conn['id']}/resources")).json()
    assert {"folder:root", "folder:fld-albor", "folder:fld-sales"} <= {r["id"] for r in roots}
    children = (
        await client.get(f"/api/v1/connections/{conn['id']}/resources", params={"parent": "folder:fld-albor"})
    ).json()
    assert {r["name"] for r in children} == {"Condiciones y políticas", "Facturación"}

    res = await client.post(
        "/api/v1/syncs",
        json={"connection_id": conn["id"], "kb_id": str(kb.id), "resource": "folder:fld-albor", "run_now": True},
    )
    assert res.status_code == 201, res.text
    sync = res.json()
    assert sync["status"] == "queued" and sync["kb_name"] == "Políticas" and sync["connector_key"] == "google_drive"
    sync_id = uuid.UUID(sync["id"])

    outcome = await execute_sync(sync_id)
    assert outcome["status"] == "success", outcome
    assert outcome["stats"]["files_ingested"] == 7 and outcome["stats"]["folders"] == 3
    files = await _files(kb.id)
    assert {f.filename for f in files} == {
        "Condiciones generales de venta.md",
        "Política de devoluciones y abonos.md",
        "Política de privacidad para clientes.md",
        "Procedimiento interno de cobro.md",
        "Facturas pendientes.csv",
        "Tarifa 2026.csv",
        "preguntas_frecuentes_clientes.md",
    }
    for f in files:
        assert f.source == "connector" and f.connection_id == uuid.UUID(conn["id"]) and f.external_id
        assert f.meta["sync_id"] == str(sync_id) and f.meta["source_version"] and f.meta["connector"] == "google_drive"
        assert f.status in ("queued", "parsing", "chunking", "embedding", "indexing", "ready")
    returns = next(f for f in files if f.filename.startswith("Política de devoluciones"))
    assert returns.meta["source_path"] == "Condiciones y políticas/Política de devoluciones y abonos.md"

    # Second run: nothing changed at the source, so nothing is downloaded or re-ingested.
    again = await execute_sync(sync_id)
    assert again["status"] == "success"
    assert again["stats"]["files_ingested"] == 0 and again["stats"]["skipped"] == 7
    assert len(await _files(kb.id)) == 7

    # Narrowing the folder prunes the files that are no longer part of the synced resource.
    res = await client.patch(f"/api/v1/syncs/{sync_id}", json={"resource": "folder:fld-policies"})
    assert res.status_code == 200
    narrowed = await execute_sync(sync_id)
    assert narrowed["stats"]["pruned"] == 4
    assert {f.filename for f in await _files(kb.id)} == {
        "Condiciones generales de venta.md",
        "Política de devoluciones y abonos.md",
        "Política de privacidad para clientes.md",
    }

    detail = (await client.get(f"/api/v1/syncs/{sync_id}")).json()
    assert detail["status"] == "success" and detail["stats"]["totals"]["runs"] == 3
    assert detail["stats"]["totals"]["files"] == 7

    run = await client.post(f"/api/v1/syncs/{sync_id}/run")
    assert run.status_code == 200 and run.json()["status"] == "queued"
    assert (await client.post(f"/api/v1/syncs/{sync_id}/run")).status_code == 409  # already queued


async def test_scheduler_queues_due_syncs(make_org, login, no_google_app) -> None:  # type: ignore[no-untyped-def]
    org, user = await make_org()
    client = await login(user.email)
    kb = await create_kb(principal_for(user.id, org.id, "owner"), name="Comercial")
    conn = (await client.post("/api/v1/connections/oauth/google_drive/start", json={})).json()["connection"]
    sync = (
        await client.post(
            "/api/v1/syncs",
            json={
                "connection_id": conn["id"],
                "kb_id": str(kb.id),
                "resource": "folder:fld-sales",
                "schedule": "*/30 * * * *",
            },
        )
    ).json()
    async with system_session() as s:
        row = await s.get(Sync, uuid.UUID(sync["id"]))
        assert row is not None and row.next_run_at is not None
        due_at = row.next_run_at
    queued: list[uuid.UUID] = []

    async def capture(sync_id: uuid.UUID) -> None:
        queued.append(sync_id)

    assert await enqueue_due_syncs(due_at - timedelta(minutes=1), send=capture) == []
    ids = await enqueue_due_syncs(due_at, send=capture)
    assert ids == [uuid.UUID(sync["id"])] == queued
    async with system_session() as s:
        row = await s.get(Sync, uuid.UUID(sync["id"]))
        assert row is not None and row.status == "queued" and row.next_run_at > due_at
    outcome = await execute_sync(uuid.UUID(sync["id"]))
    assert outcome["status"] == "success" and outcome["stats"]["files_ingested"] == 1
