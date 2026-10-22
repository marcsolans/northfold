"""GDPR data subject rights: export zip contents and verifiable deletion reports (user and organization)."""

from __future__ import annotations

import asyncio
import io
import json
import uuid
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from enterprise_support import app_client, login
from sqlalchemy import select, text

from messer_api.services import data_requests as gdpr
from messer_common.db import models as m
from messer_common.db import system_session
from messer_common.email import ConsoleEmailAdapter
from messer_common.settings import get_settings
from messer_common.storage import get_storage

MEMBER_EMAIL = "dana@datos-co.eu"


async def _seed(org_id: uuid.UUID, member: m.User, owner: m.User) -> dict[str, Any]:
    settings = get_settings()
    repo = settings.projects_dir / f"repo-{uuid.uuid4().hex[:8]}"
    repo.mkdir(parents=True)
    (repo / "README.md").write_text("# Facturas\n")
    (repo / ".git").mkdir()
    (repo / ".git" / "config").write_text("[core]\n")
    async with system_session() as s:
        project = m.Project(org_id=org_id, name="Facturas", slug="facturas", repo_path=str(repo), created_by=member.id)
        s.add(project)
        await s.flush()
        member_run, owner_run = uuid.uuid4(), uuid.uuid4()
        s.add_all(
            [
                m.Run(
                    id=member_run,
                    org_id=org_id,
                    project_id=project.id,
                    status="success",
                    user_id=member.id,
                    input={"message": "¿Cuánto debo?"},
                ),
                m.Run(id=owner_run, org_id=org_id, project_id=project.id, status="success", user_id=owner.id),
            ]
        )
        await s.flush()
        s.add_all(
            [
                m.Span(org_id=org_id, run_id=member_run, call_id="c1", kind="llm", name="agent", t0=0),
                m.Span(org_id=org_id, run_id=owner_run, call_id="c2", kind="llm", name="agent", t0=0),
                m.Conversation(
                    org_id=org_id,
                    project_id=project.id,
                    channel_key="public-chat:web",
                    workforce_name="a",
                    external_user_id=MEMBER_EMAIL,
                    messages=[{"role": "user", "content": "hola"}],
                ),
                m.Conversation(
                    org_id=org_id,
                    project_id=project.id,
                    channel_key="public-chat:web",
                    workforce_name="a",
                    external_user_id="cliente@otra.eu",
                ),
                m.Notification(org_id=org_id, user_id=member.id, kind="approval", payload={"title": "Aprobar"}),
                m.Notification(org_id=org_id, user_id=owner.id, kind="approval"),
                m.Feedback(org_id=org_id, run_id=member_run, user_id=member.id, value="up", comment="genial"),
                m.AuditLog(
                    org_id=org_id,
                    actor_id=member.id,
                    action="project.created",
                    diff={"invited": MEMBER_EMAIL, "name": "Facturas"},
                ),
                m.AuditLog(
                    org_id=org_id,
                    actor_id=owner.id,
                    action="member.role_changed",
                    diff={"email": MEMBER_EMAIL, "after": "builder"},
                ),
            ]
        )
        kb_hex = uuid.uuid4().hex[:12]
        kb = m.KnowledgeBase(
            org_id=org_id,
            name="Docs",
            embedding_model="hash-384",
            embedding_dim=384,
            schema_name=f"kb_{kb_hex}",
            reader_role=f"kb_{kb_hex}_reader",
            created_by=member.id,
        )
        s.add(kb)
        await s.flush()
        key = f"{org_id}/kb/{kb.id}/condiciones.pdf"
        s.add(
            m.KbFile(
                org_id=org_id,
                kb_id=kb.id,
                path=key,
                filename="condiciones.pdf",
                mime="application/pdf",
                size=12,
                uploaded_by=member.id,
            )
        )
    await get_storage().put(key, b"%PDF-1.7 demo", "application/pdf")
    return {"project": project, "member_run": member_run, "owner_run": owner_run, "kb": kb, "key": key, "repo": repo}


@pytest.fixture
async def org_with_member(make_org, make_user):  # type: ignore[no-untyped-def]
    member = await make_user(MEMBER_EMAIL, name="Dana")
    org, owner = await make_org(name="Datos SA", members={str(member.id): "builder"})
    seeded = await _seed(org.id, member, owner)
    return {"org": org, "owner": owner, "member": member, **seeded}


def _zip(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


async def test_self_export_contains_only_the_subjects_data(org_with_member) -> None:  # type: ignore[no-untyped-def]
    ctx = org_with_member
    ConsoleEmailAdapter.sent.clear()
    async with app_client() as member:
        await login(member, MEMBER_EMAIL)
        res = await member.post("/api/v1/data-requests", json={"kind": "export"})
        assert res.status_code == 201, res.text
        request = res.json()
        assert request["status"] == "pending" and request["reach"] == "account" and request["scope"] == "user"

        row = await gdpr.run_export(uuid.UUID(request["id"]))
        assert row is not None and row.status == "completed", row.report if row else None

        mine = (await member.get("/api/v1/data-requests/mine")).json()
        assert mine[0]["file_ready"] is True and mine[0]["expires_at"]
        link = (await member.post(f"/api/v1/data-requests/{request['id']}/link")).json()
        parts = urlsplit(link["url"])
        res = await member.get(f"{parts.path}?{parts.query}")
        assert res.status_code == 200 and res.headers["content-type"] == "application/zip"
        archive = _zip(res.content)

        bad = await member.get(f"{parts.path}?token=forged")
        assert bad.status_code == 410

    manifest = json.loads(archive["manifest.json"])
    assert manifest["scope"] == "user" and manifest["subject"]["email"] == MEMBER_EMAIL
    runs = json.loads(archive["data/runs.json"])
    assert [r["id"] for r in runs] == [str(ctx["member_run"])]
    spans = json.loads(archive["data/spans.json"])
    assert [s["run_id"] for s in spans] == [str(ctx["member_run"])]
    assert len(json.loads(archive["data/notifications.json"])) == 1
    conversations = json.loads(archive["data/conversations.json"])
    assert [c["external_user_id"] for c in conversations] == [MEMBER_EMAIL]
    assert json.loads(archive["data/users.json"])[0]["email"] == MEMBER_EMAIL
    assert any(n.startswith(f"files/{ctx['kb'].id}/") and archive[n] == b"%PDF-1.7 demo" for n in archive)
    blob = b"".join(archive.values())
    assert b"password_hash" not in blob and b"refresh_token_hash" not in blob and b"argon2" not in blob
    assert any(e.to == MEMBER_EMAIL and "data_export_ready" in e.tags for e in ConsoleEmailAdapter.sent)

    # The owner cannot download someone's account-wide export.
    async with app_client() as owner:
        await login(owner, ctx["owner"].email)
        res = await owner.post(f"/api/v1/data-requests/{request['id']}/link")
        assert res.status_code == 403
        listed = (await owner.get("/api/v1/data-requests")).json()
        assert [r["id"] for r in listed] == [request["id"]]


async def test_admin_deletes_a_member_with_verifiable_report(org_with_member) -> None:  # type: ignore[no-untyped-def]
    ctx = org_with_member
    member: m.User = ctx["member"]
    async with app_client() as owner:
        await login(owner, ctx["owner"].email)
        body = {"kind": "delete", "scope": "user", "subject_user_id": str(member.id), "confirm": "nope"}
        res = await owner.post("/api/v1/data-requests", json=body)
        assert res.status_code == 400 and res.json()["error"]["code"] == "confirmation_mismatch"
        res = await owner.post("/api/v1/data-requests", json={**body, "confirm": MEMBER_EMAIL})
        assert res.status_code == 201, res.text
        assert res.json()["reach"] == "org"
        request_id = uuid.UUID(res.json()["id"])

    row = await gdpr.run_delete(request_id)
    assert row is not None and row.status == "completed", row.report if row else None
    report = row.report["deletion"]
    assert report["verified"] is True and report["account_erased"] is True
    assert report["post_checks"] and all(c["remaining"] == 0 for c in report["post_checks"])
    assert report["deleted"]["runs"] == 1 and report["deleted"]["spans"] == 1 and report["deleted"]["memberships"] == 1
    assert report["anonymized"]["audit_log.actor_id"] == 1 and report["anonymized"]["audit_log.diff"] == 2

    async with system_session() as s:
        user = await s.get(m.User, member.id)
        assert user is not None and user.deleted_at is not None and user.email.endswith("@deleted.invalid")
        assert user.name is None
        counts = {
            sql: (await s.execute(text(sql), {"u": member.id, "e": MEMBER_EMAIL})).scalar_one()
            for sql in (
                "SELECT count(*) FROM memberships WHERE user_id = :u",
                "SELECT count(*) FROM notifications WHERE user_id = :u",
                "SELECT count(*) FROM feedback WHERE user_id = :u",
                "SELECT count(*) FROM runs WHERE user_id = :u",
                "SELECT count(*) FROM conversations WHERE external_user_id = :e",
                "SELECT count(*) FROM audit_log WHERE actor_id = :u",
                "SELECT count(*) FROM audit_log WHERE diff::text ILIKE '%' || :e || '%'",
                "SELECT count(*) FROM auth_credentials WHERE user_id = :u",
                "SELECT count(*) FROM projects WHERE created_by = :u",
                "SELECT count(*) FROM kb_files WHERE uploaded_by = :u",
            )
        }
        assert all(v == 0 for v in counts.values()), counts
        # Everyone else's data is untouched.
        assert await s.get(m.Run, ctx["owner_run"]) is not None
        others = (
            await s.execute(select(m.Conversation).where(m.Conversation.external_user_id == "cliente@otra.eu"))
        ).all()
        assert len(others) == 1
        owner_notes = (await s.execute(select(m.Notification).where(m.Notification.user_id == ctx["owner"].id))).all()
        assert len(owner_notes) == 1

    # The deleted person can no longer log in.
    async with app_client() as anon:
        res = await anon.post("/api/v1/auth/login", json={"email": MEMBER_EMAIL, "password": "Sup3rSecret!pass"})
        assert res.status_code == 401


async def test_last_owner_cannot_delete_own_account(org_with_member) -> None:  # type: ignore[no-untyped-def]
    ctx = org_with_member
    async with app_client() as owner:
        await login(owner, ctx["owner"].email)
        res = await owner.post("/api/v1/data-requests", json={"kind": "delete", "confirm": ctx["owner"].email})
        assert res.status_code == 409 and res.json()["error"]["code"] == "last_owner"
        # Members cannot act on other people.
    async with app_client() as member:
        await login(member, MEMBER_EMAIL)
        res = await member.post(
            "/api/v1/data-requests", json={"kind": "export", "scope": "user", "subject_user_id": str(ctx["owner"].id)}
        )
        assert res.status_code == 403
        res = await member.post("/api/v1/data-requests", json={"kind": "export", "scope": "org"})
        assert res.status_code == 403


async def test_org_export_then_verifiable_org_deletion(org_with_member, make_user) -> None:  # type: ignore[no-untyped-def]
    ctx = org_with_member
    org = ctx["org"]
    kb: m.KnowledgeBase = ctx["kb"]
    schema, role = kb.schema_name, kb.reader_role
    async with system_session() as s:
        await s.execute(text(f'CREATE SCHEMA "{schema}"'))
        await s.execute(text(f'CREATE TABLE "{schema}".facturas (numero text, importe numeric)'))
        await s.execute(text(f"INSERT INTO \"{schema}\".facturas VALUES ('F-1', 120.5), ('F-2', 99)"))
        await s.execute(text(f'CREATE ROLE "{role}" NOLOGIN'))
        await s.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"'))
        await s.execute(text(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO "{role}"'))
        await s.execute(text(f'GRANT USAGE ON SCHEMA messer TO "{role}"'))
        await s.execute(
            text(f"CREATE INDEX \"ix_kb_chunks_vec_{schema[3:]}\" ON kb_chunks (ordinal) WHERE kb_id = '{kb.id}'::uuid")
        )
    try:
        async with app_client() as owner:
            await login(owner, ctx["owner"].email)
            res = await owner.post("/api/v1/data-requests", json={"kind": "export", "scope": "org"})
            assert res.status_code == 201, res.text
            export_row = await gdpr.run_export(uuid.UUID(res.json()["id"]))
            assert export_row is not None and export_row.status == "completed", (
                export_row.report if export_row else None
            )
            archive = _zip(await get_storage().get(export_row.file_path or ""))
            assert json.loads(archive[f"knowledge/{kb.id}/tables/facturas.json"])[0]["numero"] == "F-1"
            assert archive["projects/facturas/README.md"] == b"# Facturas\n"
            assert not any(".git" in n for n in archive)
            assert {r["email"] for r in json.loads(archive["data/users.json"])} == {MEMBER_EMAIL, ctx["owner"].email}
            assert len(json.loads(archive["data/runs.json"])) == 2

            res = await owner.post("/api/v1/data-requests", json={"kind": "delete", "scope": "org", "confirm": "wrong"})
            assert res.status_code == 400
            res = await owner.post(
                "/api/v1/data-requests", json={"kind": "delete", "scope": "org", "confirm": org.slug}
            )
            assert res.status_code == 201, res.text
            request_id = uuid.UUID(res.json()["id"])
        async with system_session() as s:
            assert (await s.get(m.Org, org.id)).status == "blocked"  # type: ignore[union-attr]

        row = await gdpr.run_delete(request_id)
        assert row is not None and row.status == "completed", row.report if row else None
        report = row.report["deletion"]
        failing = [c for c in report["post_checks"] if c["remaining"]]
        assert report["verified"] is True, failing
        assert report["organization"]["slug"] == org.slug and report["deleted"]["runs"] == 2

        async with system_session() as s:
            assert await s.get(m.Org, org.id) is None
            kept = await s.get(m.DataRequest, request_id)
            assert kept is not None and kept.org_id is None and kept.report["deletion"]["verified"] is True
            assert (
                await s.execute(text("SELECT count(*) FROM pg_namespace WHERE nspname = :n"), {"n": schema})
            ).scalar_one() == 0
            assert (
                await s.execute(text("SELECT count(*) FROM pg_roles WHERE rolname = :r"), {"r": role})
            ).scalar_one() == 0
            audit = (await s.execute(select(m.AuditLog).where(m.AuditLog.action == "org.deleted"))).scalar_one()
            assert audit.org_id is None and audit.entity_id == str(org.id)
            assert await s.get(m.User, ctx["member"].id) is not None  # accounts are kept
        assert not await get_storage().exists(ctx["key"])
        assert not await asyncio.to_thread(Path(ctx["repo"]).exists)
        assert not await asyncio.to_thread((get_settings().storage_dir / str(org.id)).exists)

        admin = await make_user("ops@messer-ops.eu", superadmin=True)
        async with app_client() as backoffice:
            await login(backoffice, admin.email)
            listed = (await backoffice.get("/api/v1/admin/data-requests", params={"kind": "delete"})).json()
            assert listed[0]["id"] == str(request_id) and listed[0]["org_name"] == "Datos SA"
    finally:
        async with system_session() as s:
            await s.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await gdpr.drop_reader_role(s, role)


async def test_backoffice_endpoints_require_superadmin(org_with_member, make_user) -> None:  # type: ignore[no-untyped-def]
    ctx = org_with_member
    async with app_client() as owner:
        await login(owner, ctx["owner"].email)
        res = await owner.get("/api/v1/admin/data-requests")
        assert res.status_code == 403
    admin = await make_user("root@messer-ops.eu", superadmin=True)
    async with app_client() as backoffice:
        await login(backoffice, admin.email)
        res = await backoffice.post(
            "/api/v1/admin/data-requests",
            json={"org_id": str(ctx["org"].id), "kind": "export", "scope": "user", "subject_email": MEMBER_EMAIL},
        )
        assert res.status_code == 201, res.text
        assert res.json()["reach"] == "account" and res.json()["subject"]["email"] == MEMBER_EMAIL
        row = await gdpr.run_export(uuid.UUID(res.json()["id"]))
        assert row is not None and row.status == "completed"
        link = await backoffice.post(f"/api/v1/admin/data-requests/{row.id}/link")
        assert link.status_code == 200 and "/download?token=" in link.json()["url"]
