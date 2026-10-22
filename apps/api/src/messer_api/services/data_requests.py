"""GDPR data subject rights (spec §9.3): export everything held about a user or an organization as a zip,
and delete it verifiably.

Scopes and reach
----------------
* ``scope = "org"``  — the whole organization. Export: one JSON file per table (rows with ``org_id``), the
  members' profiles, every knowledge-base table and the uploaded files and project repositories. Delete: storage
  objects, project repositories, knowledge-base schemas, reader roles and indexes, every row with ``org_id``,
  and the organization itself. The ``data_requests`` row survives (``org_id`` becomes NULL) with the report.
* ``scope = "user"`` — one person. ``reach`` (stored in ``report.params``) is ``"org"`` when an organization
  admin asks (only that organization's rows; the account is erased only if the person belongs to no other
  organization) and ``"account"`` when the person asks for themselves or a superadmin acts (every organization
  plus the account itself).

The table set is discovered from the database catalog, so tables added by other areas are covered: columns
that reference ``users.id`` are nulled (or their rows deleted when NOT NULL), rows keyed by the person's
external ids are deleted, and secrets (hashes, encrypted values) are never exported. Every deletion ends with
post-check queries whose results (all zero) are stored in ``data_requests.report``.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import re
import shutil
import tempfile
import uuid
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common.db import Principal, system_session
from messer_common.db.models import DataRequest, Membership, Org, User
from messer_common.email import send_template
from messer_common.events import get_redis
from messer_common.logging import get_logger
from messer_common.queue import Jobs, enqueue
from messer_common.security import sign_payload
from messer_common.settings import get_settings
from messer_common.storage import LocalStorage, Storage, StorageError, SupabaseStorage, get_storage

from ..errors import ApiError, Conflict

log = get_logger("messer.gdpr")

GLOBAL_TABLES = frozenset(
    {
        "alembic_version",
        "plans",
        "model_prices",
        "templates",
        "connectors",
        "feature_flags",
        "stripe_events",
        "service_health",
    }
)
# Account-level tables (no org_id) and the column that identifies the person.
ACCOUNT_TABLES: dict[str, str] = {
    "auth_credentials": "user_id",
    "auth_sessions": "user_id",
    "one_time_tokens": "user_id",
}
SENSITIVE_COLUMNS = frozenset(
    {
        "password_hash",
        "refresh_token_hash",
        "token_hash",
        "hashed_token",
        "hashed_key",
        "mfa_secret_encrypted",
        "mfa_recovery_codes",
        "config_encrypted",
        "credentials",
        "encrypted_value",
        "webhook_secret",
        "secret",
        "enrollment_token_hash",
        "verification_token",
        "credentials_encrypted",
    }
)
SKIP_TYPES = frozenset({"vector", "tsvector", "bytea"})
USER_REF_NAMES = frozenset(
    {
        "user_id",
        "actor_id",
        "created_by",
        "author_id",
        "decided_by",
        "uploaded_by",
        "forced_by",
        "invited_by",
        "assigned_user_id",
        "verified_by",
        "impersonated_by",
        "requested_by",
        "owner_id",
        "updated_by",
    }
)
EXTERNAL_ID_COLUMNS = frozenset({"external_user_id"})
# Tables never modified by a user deletion: the request itself is the (pseudonymous) proof of compliance.
RETAINED_TABLES = frozenset({"data_requests", "users"})
_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


class DataRequestError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


# ============================================================================= catalog


@dataclass(slots=True)
class Column:
    name: str
    udt_name: str
    nullable: bool


@dataclass(slots=True)
class Table:
    name: str
    columns: list[Column] = field(default_factory=list)
    user_columns: list[str] = field(default_factory=list)

    @property
    def has_org(self) -> bool:
        return any(c.name == "org_id" for c in self.columns)

    def column(self, name: str) -> Column | None:
        return next((c for c in self.columns if c.name == name), None)

    @property
    def exportable(self) -> list[str]:
        return [
            c.name
            for c in self.columns
            if c.name not in SENSITIVE_COLUMNS
            and not c.name.endswith(("_hash", "_encrypted"))
            and not c.name.startswith("hashed_")
            and c.udt_name not in SKIP_TYPES
        ]

    @property
    def external_columns(self) -> list[str]:
        return [c.name for c in self.columns if c.name in EXTERNAL_ID_COLUMNS]


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


async def introspect(session: AsyncSession) -> dict[str, Table]:
    rows = await session.execute(
        text(
            "SELECT c.table_name, c.column_name, c.udt_name, c.is_nullable = 'YES' "
            "FROM information_schema.columns c JOIN information_schema.tables t "
            "ON t.table_schema = c.table_schema AND t.table_name = c.table_name "
            "WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE' "
            "ORDER BY c.table_name, c.ordinal_position"
        )
    )
    tables: dict[str, Table] = {}
    for table_name, column_name, udt_name, nullable in rows:
        tables.setdefault(table_name, Table(table_name)).columns.append(Column(column_name, udt_name, bool(nullable)))
    fks = await session.execute(
        text(
            "SELECT cl.relname, a.attname FROM pg_constraint con "
            "JOIN pg_class cl ON cl.oid = con.conrelid JOIN pg_namespace n ON n.oid = cl.relnamespace "
            "JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = ANY(con.conkey) "
            "WHERE con.contype = 'f' AND n.nspname = 'public' AND con.confrelid = 'public.users'::regclass"
        )
    )
    fk_cols: dict[str, set[str]] = {}
    for table_name, column_name in fks:
        fk_cols.setdefault(table_name, set()).add(column_name)
    for table in tables.values():
        names = {c.name for c in table.columns}
        refs = (fk_cols.get(table.name, set()) | (USER_REF_NAMES & names)) - {"id"}
        # Only uuid columns can hold user ids.
        table.user_columns = sorted(r for r in refs if (col := table.column(r)) is not None and col.udt_name == "uuid")
    for name in GLOBAL_TABLES:
        tables.pop(name, None)
    return tables


# ============================================================================= requests


def request_reach(req: DataRequest) -> str:
    return str((req.report or {}).get("params", {}).get("reach") or "org")


def download_url(req: DataRequest) -> tuple[str, datetime]:
    settings = get_settings()
    ttl = timedelta(days=settings.messer_data_export_ttl_days)
    expires = (req.completed_at or datetime.now(UTC)) + ttl
    remaining = int((expires - datetime.now(UTC)).total_seconds())
    if remaining <= 0:
        raise ApiError("La exportación ha caducado. Solicita una nueva.", code="export_expired", status_code=410)
    token = sign_payload({"purpose": "data_export", "dr": str(req.id)}, ttl_s=remaining)
    return f"{settings.messer_web_url.rstrip('/')}/api/v1/data-requests/{req.id}/download?token={token}", expires


async def _owner_conflicts(session: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID | None) -> list[str]:
    """Organizations in which ``user_id`` is the only owner (restricted to ``org_id`` when given)."""
    sql = (
        "SELECT o.name FROM memberships m JOIN orgs o ON o.id = m.org_id "
        "WHERE m.user_id = :uid AND m.role = 'owner' "
        "AND (SELECT count(*) FROM memberships x WHERE x.org_id = m.org_id AND x.role = 'owner') = 1"
    )
    params: dict[str, Any] = {"uid": user_id}
    if org_id is not None:
        sql += " AND m.org_id = :org"
        params["org"] = org_id
    return [r[0] for r in await session.execute(text(sql), params)]


async def create_request(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    requester: Principal,
    kind: str,
    scope: str,
    subject_user_id: uuid.UUID | None,
    reach: str,
) -> DataRequest:
    """Insert a pending request (system session; the caller has authorized it) and audit it."""
    if kind not in ("export", "delete") or scope not in ("user", "org") or reach not in ("org", "account"):
        raise ApiError("Solicitud no válida", code="invalid_request")
    if scope == "user" and subject_user_id is None:
        raise ApiError("Indica la persona", code="subject_required")
    same_subject = (
        DataRequest.subject_user_id == subject_user_id if scope == "user" else DataRequest.subject_user_id.is_(None)
    )
    active = (
        await session.execute(
            select(DataRequest.id).where(
                DataRequest.org_id == org_id,
                DataRequest.kind == kind,
                DataRequest.scope == scope,
                same_subject,
                DataRequest.status.in_(("pending", "running")),
            )
        )
    ).first()
    if active is not None:
        raise Conflict("Ya hay una solicitud igual en curso", code="request_in_progress")
    if kind == "delete" and scope == "user" and subject_user_id is not None:
        conflicts = await _owner_conflicts(session, subject_user_id, None if reach == "account" else org_id)
        if conflicts:
            raise Conflict(
                "Esta persona es la única propietaria de: "
                + ", ".join(conflicts)
                + ". Transfiere la propiedad o elimina la organización antes.",
                code="last_owner",
                details={"orgs": conflicts},
            )
    req = DataRequest(
        org_id=org_id,
        user_id=requester.user_id,
        subject_user_id=subject_user_id if scope == "user" else None,
        scope=scope,
        kind=kind,
        status="pending",
        report={"params": {"reach": reach, "requested_by_superadmin": requester.is_superadmin}},
    )
    session.add(req)
    await session.flush()
    if kind == "delete" and scope == "org":
        org = await session.get(Org, org_id)
        if org is not None:
            org.status = "blocked"
            org.blocked_reason = "Eliminación de la organización en curso"
    await audit.record(
        session,
        action=f"data_request.{kind}_requested",
        principal=requester,
        org_id=org_id,
        entity_type="data_request",
        entity_id=req.id,
        diff={"scope": scope, "reach": reach, "subject_user_id": str(subject_user_id) if subject_user_id else None},
    )
    return req


async def dispatch(req_id: uuid.UUID, kind: str) -> None:
    """Hand the request to the worker (after the creating transaction committed)."""
    job = Jobs.DATA_EXPORT if kind == "export" else Jobs.DATA_DELETE
    await enqueue(job, str(req_id), _job_id=f"data_request:{req_id}:{datetime.now(UTC).timestamp():.0f}")


# ============================================================================= JSON


def _json_default(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes | bytearray | memoryview):
        return base64.b64encode(bytes(value)).decode()
    if isinstance(value, set | frozenset | tuple):
        return list(value)
    return str(value)


async def _write_query(
    zf: zipfile.ZipFile, arcname: str, session: AsyncSession, sql: str, params: dict[str, Any]
) -> int:
    count = 0
    result = await session.stream(text(sql), params)
    with zf.open(arcname, "w") as fh:
        fh.write(b"[")
        async for row in result.mappings():
            fh.write(
                (b",\n" if count else b"\n") + json.dumps(dict(row), default=_json_default, ensure_ascii=False).encode()
            )
            count += 1
        fh.write(b"\n]\n" if count else b"]\n")
    return count


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^\w.\- ]+", "_", value).strip(" .") or "file"
    return cleaned[:120]


# ============================================================================= predicates


@dataclass(slots=True)
class Subject:
    user_id: uuid.UUID
    email: str
    identifiers: list[str]


def _user_predicate(table: Table, subject: Subject) -> str | None:
    parts = [f"{q(c)} = :uid" for c in table.user_columns]
    parts += [f"{q(c)} = ANY(:idents)" for c in table.external_columns]
    if table.name == "invitations" and table.column("email") is not None:
        parts.append("lower(email) = :email")
    return "(" + " OR ".join(parts) + ")" if parts else None


def _runs_predicate(tables: dict[str, Table], subject: Subject) -> str | None:
    runs = tables.get("runs")
    return _user_predicate(runs, subject) if runs is not None else None


# ============================================================================= export


async def _export(req: DataRequest, subject: Subject | None) -> dict[str, Any]:
    assert req.org_id is not None
    reach = request_reach(req)
    storage = get_storage()
    settings = get_settings()
    counts: dict[str, int] = {}
    files: list[tuple[str, str]] = []  # (storage key, archive name)
    repos: list[tuple[str, str]] = []  # (path, archive prefix)
    missing: list[str] = []
    params: dict[str, Any] = {"org": req.org_id}
    if subject is not None:
        params |= {"uid": subject.user_id, "idents": subject.identifiers, "email": subject.email}

    with tempfile.TemporaryDirectory(prefix="messer-export-") as tmp:
        zip_path = Path(tmp) / "export.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            async with system_session() as s:
                await s.connection(execution_options={"isolation_level": "REPEATABLE READ"})  # consistent snapshot
                tables = await introspect(s)
                for table in sorted(tables.values(), key=lambda t: t.name):
                    cols = ", ".join(q(c) for c in table.exportable)
                    if not cols:
                        continue
                    where: str | None = None
                    if req.scope == "org":
                        if table.has_org:
                            where = "org_id = :org"
                    else:
                        assert subject is not None
                        if table.name == "spans" and (runs_pred := _runs_predicate(tables, subject)):
                            where = f"run_id IN (SELECT id FROM runs WHERE {runs_pred}" + (
                                " AND org_id = :org)" if reach == "org" else ")"
                            )
                        elif table.has_org:
                            pred = _user_predicate(table, subject)
                            if pred:
                                where = pred + (" AND org_id = :org" if reach == "org" else "")
                        elif reach == "account" and table.name in ACCOUNT_TABLES and table.name != "one_time_tokens":
                            where = f"{q(ACCOUNT_TABLES[table.name])} = :uid"
                        elif reach == "account" and table.name == "contact_requests":
                            where = "lower(email) = :email"
                    if where is None:
                        continue
                    if table.name == "users":
                        continue
                    sql = f"SELECT {cols} FROM public.{q(table.name)} WHERE {where}"
                    counts[table.name] = await _write_query(zf, f"data/{table.name}.json", s, sql, params)

                profile_cols = "id, email, name, locale, created_at, last_login_at"
                if req.scope == "org":
                    counts["users"] = await _write_query(
                        zf,
                        "data/users.json",
                        s,
                        f"SELECT {profile_cols} FROM users WHERE id IN (SELECT user_id FROM memberships WHERE org_id = :org)",
                        params,
                    )
                else:
                    counts["users"] = await _write_query(
                        zf, "data/users.json", s, f"SELECT {profile_cols}, status FROM users WHERE id = :uid", params
                    )

                file_sql = "SELECT id, kb_id, path, filename FROM kb_files WHERE "
                if req.scope == "org":
                    file_sql += "org_id = :org"
                else:
                    file_sql += "uploaded_by = :uid" + (" AND org_id = :org" if reach == "org" else "")
                if "kb_files" in tables:
                    for fid, kb_id, path, filename in await s.execute(text(file_sql), params):
                        files.append((str(path), f"files/{kb_id}/{fid}-{_safe_name(str(filename))}"))

                if req.scope == "org" and "knowledge_bases" in tables:
                    kbs = await s.execute(
                        text("SELECT id, schema_name FROM knowledge_bases WHERE org_id = :org"), params
                    )
                    for kb_id, schema_name in kbs:
                        if not schema_name or not _IDENT_RE.match(str(schema_name)):
                            continue
                        kb_tables = await s.execute(
                            text(
                                "SELECT table_name FROM information_schema.tables WHERE table_schema = :schema "
                                "AND table_type = 'BASE TABLE' ORDER BY table_name"
                            ),
                            {"schema": schema_name},
                        )
                        for (table_name,) in kb_tables.all():
                            arc = f"knowledge/{kb_id}/tables/{_safe_name(str(table_name))}.json"
                            counts[f"kb:{kb_id}:{table_name}"] = await _write_query(
                                zf, arc, s, f"SELECT * FROM {q(str(schema_name))}.{q(str(table_name))}", {}
                            )
                if req.scope == "org" and "projects" in tables:
                    for pid, slug, repo_path in await s.execute(
                        text("SELECT id, slug, repo_path FROM projects WHERE org_id = :org"), params
                    ):
                        if repo_path:
                            repos.append((str(repo_path), f"projects/{_safe_name(str(slug or pid))}"))

            for key, arcname in files:
                try:
                    zf.writestr(arcname, await storage.get(key))
                except StorageError:
                    missing.append(key)
            repo_root = settings.projects_dir.resolve()
            repo_files = 0
            for repo_path, prefix in repos:
                root = Path(repo_path)
                root = root if root.is_absolute() else repo_root / root
                if not root.exists():
                    continue
                for file in sorted(root.rglob("*")):
                    if file.is_symlink() or not file.is_file() or ".git" in file.relative_to(root).parts:
                        continue
                    zf.write(file, f"{prefix}/{file.relative_to(root).as_posix()}")
                    repo_files += 1

            manifest = {
                "format": "messer-data-export/1",
                "request_id": str(req.id),
                "organization_id": str(req.org_id),
                "scope": req.scope,
                "reach": reach,
                "subject": {"user_id": str(subject.user_id), "email": subject.email} if subject else None,
                "generated_at": datetime.now(UTC).isoformat(),
                "tables": counts,
                "files": len(files) - len(missing),
                "missing_files": missing,
                "repository_files": repo_files,
                "notes": [
                    "Cada archivo data/<tabla>.json contiene las filas de esa tabla en JSON.",
                    "Por seguridad no se exportan contraseñas, hashes de tokens ni secretos cifrados.",
                    "Each data/<table>.json file holds that table's rows as JSON. Passwords, token hashes and "
                    "encrypted secrets are never exported.",
                ],
            }
            zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        data = await asyncio.to_thread(zip_path.read_bytes)

    key = f"{req.org_id}/data-requests/{req.id}.zip"
    await storage.put(key, data, "application/zip")
    return {
        "file_path": key,
        "bytes": len(data),
        "tables": counts,
        "files": manifest["files"],
        "missing_files": missing,
    }


async def run_export(request_id: uuid.UUID) -> DataRequest | None:
    req = await _claim(request_id, "export")
    if req is None:
        return None
    subject: Subject | None = None
    try:
        if req.org_id is None:
            raise DataRequestError("org_missing", "La organización ya no existe")
        if req.scope == "user":
            subject = await _load_subject(req.subject_user_id)
        result = await _export(req, subject)
    except (DataRequestError, StorageError, OSError) as exc:
        return await _fail(req, exc)
    except Exception as exc:
        log.exception("gdpr.export_failed", request_id=str(request_id))
        return await _fail(req, exc)
    now = datetime.now(UTC)
    ttl = timedelta(days=get_settings().messer_data_export_ttl_days)
    async with system_session() as s:
        row = await s.get(DataRequest, request_id)
        assert row is not None
        row.status = "completed"
        row.file_path = result["file_path"]
        row.completed_at = now
        row.report = {
            **(row.report or {}),
            "export": {k: v for k, v in result.items() if k != "file_path"},
            "expires_at": (now + ttl).isoformat(),
        }
        await audit.record(
            s,
            action="data_request.export_completed",
            org_id=row.org_id,
            entity_type="data_request",
            entity_id=row.id,
            diff={"bytes": result["bytes"], "tables": len(result["tables"]), "files": result["files"]},
        )
        requester = await s.get(User, row.user_id) if row.user_id else None
        url, _ = download_url(row)
    if requester is not None and requester.deleted_at is None:
        try:
            await send_template(requester.email, "data_export_ready", {"url": url}, requester.locale)
        except Exception as exc:  # the export is ready even if the email fails; the UI shows the link
            log.warning("gdpr.export_email_failed", request_id=str(request_id), error=str(exc))
    return row


# ============================================================================= delete


async def _load_subject(user_id: uuid.UUID | None) -> Subject:
    if user_id is None:
        raise DataRequestError("subject_missing", "Falta la persona de la solicitud")
    async with system_session() as s:
        user = await s.get(User, user_id)
    if user is None:
        raise DataRequestError("subject_missing", "La persona ya no existe")
    return Subject(user_id=user.id, email=user.email.lower(), identifiers=[str(user.id), user.email.lower()])


def _pg_regex_escape(value: str) -> str:
    return re.sub(r"([.+*?^$()\[\]{}|\\])", r"\\\1", value)


@dataclass(slots=True)
class _Check:
    name: str
    sql: str
    params: dict[str, Any]


async def _count(session: AsyncSession, sql: str, params: dict[str, Any]) -> int:
    return int((await session.execute(text(sql), params)).scalar_one())


async def _exec(session: AsyncSession, sql: str, params: dict[str, Any]) -> int:
    result = await session.execute(text(sql), params)
    return int(getattr(result, "rowcount", 0) or 0)


async def _delete_user(req: DataRequest) -> dict[str, Any]:
    subject = await _load_subject(req.subject_user_id)
    reach = request_reach(req)
    org_scoped = reach == "org"
    org_sql = " AND org_id = :org" if org_scoped else ""
    params: dict[str, Any] = {
        "uid": subject.user_id,
        "idents": subject.identifiers,
        "email": subject.email,
        "org": req.org_id,
    }
    deleted: dict[str, int] = {}
    anonymized: dict[str, int] = {}
    checks: list[_Check] = []
    account_erased = False

    async with system_session() as s:
        conflicts = await _owner_conflicts(s, subject.user_id, req.org_id if org_scoped else None)
        if conflicts:
            raise DataRequestError(
                "last_owner", "Es la única propietaria de: " + ", ".join(conflicts), {"orgs": conflicts}
            )
        tables = await introspect(s)

        # 1. traces of the person's runs, then every org table keyed by the person (rows are personal data)
        handled: set[tuple[str, str]] = set()
        if (runs_pred := _runs_predicate(tables, subject)) and "spans" in tables:
            sql_pred = f"run_id IN (SELECT id FROM runs WHERE {runs_pred}{org_sql})"
            deleted["spans"] = await _exec(s, f"DELETE FROM spans WHERE {sql_pred}", params)
            checks.append(_Check("spans", f"SELECT count(*) FROM spans WHERE {sql_pred}", params))
        personal = (
            "runs",
            "conversations",
            "feedback",
            "notifications",
            "composer_sessions",
            "scim_group_members",
            "org_identities",
            "invitations",
            "memberships",
        )
        for name in personal:
            table = tables.get(name)
            pred = _user_predicate(table, subject) if table is not None else None
            if table is None or pred is None:
                continue
            scoped = pred + (org_sql if table.has_org else "")
            deleted[name] = await _exec(s, f"DELETE FROM public.{q(name)} WHERE {scoped}", params)
            checks.append(_Check(name, f"SELECT count(*) FROM public.{q(name)} WHERE {scoped}", params))
            handled.update((name, c) for c in table.user_columns)

        # 2. audit trail: anonymize the actor and redact the email inside diffs (insert-only for the app role)
        if "audit_log" in tables:
            for col in ("actor_id", "impersonated_by"):
                anonymized[f"audit_log.{col}"] = await _exec(
                    s, f"UPDATE audit_log SET {col} = NULL WHERE {col} = :uid{org_sql}", params
                )
                checks.append(
                    _Check(f"audit_log.{col}", f"SELECT count(*) FROM audit_log WHERE {col} = :uid{org_sql}", params)
                )
                handled.add(("audit_log", col))
            redact = {**params, "pattern": _pg_regex_escape(subject.email), "like": f"%{subject.email}%"}
            anonymized["audit_log.diff"] = await _exec(
                s,
                "UPDATE audit_log SET diff = regexp_replace(diff::text, :pattern, '[deleted]', 'gi')::jsonb "
                f"WHERE diff::text ILIKE :like{org_sql}",
                redact,
            )
            checks.append(
                _Check(
                    "audit_log.diff", f"SELECT count(*) FROM audit_log WHERE diff::text ILIKE :like{org_sql}", redact
                )
            )

        # 3. any other reference to the person: NULL it, or delete the row when the column is NOT NULL
        for table in sorted(tables.values(), key=lambda t: t.name):
            if table.name in RETAINED_TABLES or table.name in ACCOUNT_TABLES:
                continue
            if not table.has_org and org_scoped:
                continue
            for col in table.user_columns:
                if (table.name, col) in handled:
                    continue
                column = table.column(col)
                assert column is not None
                scope_sql = org_sql if table.has_org else ""
                where = f"{q(col)} = :uid{scope_sql}"
                if column.nullable:
                    anonymized[f"{table.name}.{col}"] = await _exec(
                        s, f"UPDATE public.{q(table.name)} SET {q(col)} = NULL WHERE {where}", params
                    )
                else:
                    deleted[f"{table.name}.{col}"] = await _exec(
                        s, f"DELETE FROM public.{q(table.name)} WHERE {where}", params
                    )
                checks.append(
                    _Check(f"{table.name}.{col}", f"SELECT count(*) FROM public.{q(table.name)} WHERE {where}", params)
                )
            for col in table.external_columns:
                if table.name in personal or table.name == "spans":
                    continue
                where = f"{q(col)} = ANY(:idents)" + (org_sql if table.has_org else "")
                deleted[f"{table.name}.{col}"] = await _exec(
                    s, f"DELETE FROM public.{q(table.name)} WHERE {where}", params
                )
                checks.append(
                    _Check(f"{table.name}.{col}", f"SELECT count(*) FROM public.{q(table.name)} WHERE {where}", params)
                )

        # 4. the account itself (person asked, superadmin acted, or no organization left)
        remaining_memberships = await _count(s, "SELECT count(*) FROM memberships WHERE user_id = :uid", params)
        if reach == "account" or remaining_memberships == 0:
            if remaining_memberships:
                deleted["memberships:other_orgs"] = await _exec(
                    s, "DELETE FROM memberships WHERE user_id = :uid", params
                )
            for name, col in ACCOUNT_TABLES.items():
                if name in tables:
                    deleted[name] = await _exec(s, f"DELETE FROM public.{q(name)} WHERE {q(col)} = :uid", params)
                    checks.append(_Check(name, f"SELECT count(*) FROM public.{q(name)} WHERE {q(col)} = :uid", params))
            if "contact_requests" in tables:
                deleted["contact_requests"] = await _exec(
                    s, "DELETE FROM contact_requests WHERE lower(email) = :email", params
                )
                checks.append(
                    _Check(
                        "contact_requests", "SELECT count(*) FROM contact_requests WHERE lower(email) = :email", params
                    )
                )
            await s.execute(
                text(
                    "UPDATE users SET email = :anon, name = NULL, avatar = NULL, status = 'deleted', "
                    "is_superadmin = false, last_login_at = NULL, deleted_at = now() WHERE id = :uid"
                ),
                {**params, "anon": f"deleted-{subject.user_id.hex}@deleted.invalid"},
            )
            checks.append(
                _Check("memberships:any_org", "SELECT count(*) FROM memberships WHERE user_id = :uid", params)
            )
            checks.append(
                _Check(
                    "users:personal_data",
                    "SELECT count(*) FROM users WHERE id = :uid AND (lower(email) = :email OR name IS NOT NULL "
                    "OR avatar IS NOT NULL OR deleted_at IS NULL)",
                    params,
                )
            )
            account_erased = True

    supabase = await _delete_supabase_user(subject.user_id) if account_erased else None
    post_checks = await _run_checks(checks)
    return {
        "subject": {"user_id": str(subject.user_id)},
        "reach": reach,
        "deleted": {k: v for k, v in deleted.items() if v},
        "anonymized": {k: v for k, v in anonymized.items() if v},
        "account_erased": account_erased,
        "supabase_auth": supabase,
        "retained": ["data_requests (prueba pseudónima de la solicitud / pseudonymous proof of the request)"],
        "post_checks": post_checks,
        "verified": all(c["remaining"] == 0 for c in post_checks),
        "_notify_email": subject.email,
    }


async def _run_checks(checks: Iterable[_Check]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    async with system_session() as s:
        for check in checks:
            remaining = await _count(s, check.sql, check.params)
            out.append({"check": check.name, "sql": check.sql, "remaining": remaining})
    return out


async def _delete_supabase_user(user_id: uuid.UUID) -> str | None:
    settings = get_settings()
    if not settings.has_supabase_storage:
        return None
    url = f"{settings.supabase_url.rstrip('/')}/auth/v1/admin/users/{user_id}"
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.delete(url, headers=headers)
    except httpx.HTTPError as exc:
        return f"error: {exc}"
    return "deleted" if res.status_code in (200, 204, 404) else f"error: {res.status_code}"


async def purge_org_storage(storage: Storage, org_id: uuid.UUID) -> dict[str, Any]:
    """Remove every object under the organization's prefix (local directory or Supabase bucket)."""
    if isinstance(storage, LocalStorage):
        root = (storage.root / str(org_id)).resolve()
        if storage.root.resolve() in root.parents and root.exists():
            await asyncio.to_thread(shutil.rmtree, root)
        return {"backend": "local", "prefix_exists": root.exists()}
    if isinstance(storage, SupabaseStorage):
        bucket = f"org-{org_id}"
        async with httpx.AsyncClient(headers=storage.headers, timeout=120) as client:
            await client.post(f"{storage.base}/bucket/{bucket}/empty")
            res = await client.delete(f"{storage.base}/bucket/{bucket}")
            check = await client.get(f"{storage.base}/bucket/{bucket}")
        return {
            "backend": "supabase",
            "bucket_deleted": res.status_code in (200, 204, 400, 404),
            "prefix_exists": check.status_code == 200,
        }
    return {"backend": type(storage).__name__, "prefix_exists": None}


async def drop_reader_role(session: AsyncSession, role: str) -> str | None:
    """Revoke every privilege granted to a knowledge-base reader role, then drop it.

    ``DROP OWNED BY`` needs the privileges of the role, which the owner connection does not hold, so grants are
    found in the catalogs (schemas, relations, functions, the database) and revoked one by one. Returns an error
    message when the role could not be dropped (the post-check reports it).
    """
    if not _IDENT_RE.match(role):
        return "invalid role name"
    oid = (await session.execute(text("SELECT oid FROM pg_roles WHERE rolname = :r"), {"r": role})).scalar_one_or_none()
    if oid is None:
        return None
    grants: list[str] = []
    for (schema,) in await session.execute(
        text("SELECT n.nspname FROM pg_namespace n, aclexplode(n.nspacl) a WHERE a.grantee = :oid"), {"oid": oid}
    ):
        grants.append(f"SCHEMA {q(str(schema))}")
    for schema, rel, kind in await session.execute(
        text(
            "SELECT n.nspname, c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace, "
            "aclexplode(c.relacl) a WHERE a.grantee = :oid"
        ),
        {"oid": oid},
    ):
        grants.append(f"{'SEQUENCE' if kind == 'S' else 'TABLE'} {q(str(schema))}.{q(str(rel))}")
    for (signature,) in await session.execute(
        text("SELECT p.oid::regprocedure::text FROM pg_proc p, aclexplode(p.proacl) a WHERE a.grantee = :oid"),
        {"oid": oid},
    ):
        grants.append(f"FUNCTION {signature}")
    try:
        async with session.begin_nested():
            for target in dict.fromkeys(grants):
                await session.execute(text(f"REVOKE ALL ON {target} FROM {q(role)}"))
            await session.execute(text(f"REVOKE ALL ON DATABASE {q(await _database_name(session))} FROM {q(role)}"))
            await session.execute(text(f"DROP ROLE IF EXISTS {q(role)}"))
    except Exception as exc:  # reported in the deletion report; never leaves the transaction broken
        return f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"
    return None


async def _database_name(session: AsyncSession) -> str:
    return str((await session.execute(text("SELECT current_database()"))).scalar_one())


async def _cancel_stripe(subscription_id: str | None) -> str | None:
    settings = get_settings()
    if not subscription_id or not settings.has_stripe:
        return None
    import stripe

    def cancel() -> None:
        stripe.Subscription.cancel(subscription_id, api_key=settings.stripe_secret_key)  # type: ignore[call-arg]

    try:
        await asyncio.to_thread(cancel)
    except Exception as exc:  # billing must not block the erasure; reported for follow-up
        return f"error: {exc}"
    return "canceled"


async def _delete_org(req: DataRequest) -> dict[str, Any]:
    if req.org_id is None:
        raise DataRequestError("org_missing", "La organización ya no existe")
    org_id = req.org_id
    params: dict[str, Any] = {"org": org_id, "req": req.id}
    storage = get_storage()
    settings = get_settings()
    async with system_session() as s:
        org = await s.get(Org, org_id)
        if org is None:
            raise DataRequestError("org_missing", "La organización ya no existe")
        snapshot = {"id": str(org.id), "name": org.name, "slug": org.slug}
        tables = await introspect(s)
        org_tables = sorted(t.name for t in tables.values() if t.has_org)
        before = {
            t: await _count(s, f"SELECT count(*) FROM public.{q(t)} WHERE org_id = :org", params) for t in org_tables
        }
        kbs = (
            (
                await s.execute(
                    text("SELECT id, schema_name, reader_role FROM knowledge_bases WHERE org_id = :org"), params
                )
            ).all()
            if "knowledge_bases" in tables
            else []
        )
        keys: list[str] = []
        for table, col in (("kb_files", "path"), ("kb_backups", "path"), ("data_requests", "file_path")):
            if table in tables and tables[table].column(col) is not None:
                keys += [
                    str(r[0])
                    for r in await s.execute(
                        text(f"SELECT {q(col)} FROM public.{q(table)} WHERE org_id = :org AND {q(col)} IS NOT NULL"),
                        params,
                    )
                ]
        repos = (
            [
                str(r[0])
                for r in await s.execute(text("SELECT repo_path FROM projects WHERE org_id = :org"), params)
                if r[0]
            ]
            if "projects" in tables
            else []
        )
        stripe_sub = (
            (
                await s.execute(text("SELECT stripe_subscription_id FROM subscriptions WHERE org_id = :org"), params)
            ).scalar_one_or_none()
            if "subscriptions" in tables
            else None
        )
        member_ids = [
            r[0] for r in await s.execute(text("SELECT user_id FROM memberships WHERE org_id = :org"), params)
        ]

    # ---- outside the database: storage, repositories, billing
    storage_errors: list[str] = []
    for key in dict.fromkeys(keys):
        try:
            await storage.delete(key)
        except StorageError as exc:
            storage_errors.append(f"{key}: {exc}")
    storage_purge = await purge_org_storage(storage, org_id)
    repo_root = settings.projects_dir.resolve()
    repo_paths: list[Path] = []
    for raw in repos:
        path = Path(raw)
        path = (path if path.is_absolute() else repo_root / path).resolve()
        if repo_root in path.parents and path.exists():
            await asyncio.to_thread(shutil.rmtree, path, True)
        repo_paths.append(path)
    stripe_result = await _cancel_stripe(stripe_sub)

    # ---- database: knowledge schemas, roles, per-KB indexes, rows, the organization
    role_errors: list[str] = []
    async with system_session() as s:
        for kb_id, schema_name, reader_role in kbs:
            if schema_name and _IDENT_RE.match(str(schema_name)):
                await s.execute(text(f"DROP SCHEMA IF EXISTS {q(str(schema_name))} CASCADE"))
            indexes = await s.execute(
                text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND indexdef LIKE :pattern"),
                {"pattern": f"%{kb_id}%"},
            )
            for (index_name,) in indexes.all():
                await s.execute(text(f"DROP INDEX IF EXISTS public.{q(str(index_name))}"))
            if reader_role and _IDENT_RE.match(str(reader_role)):
                error = await drop_reader_role(s, str(reader_role))
                if error:
                    role_errors.append(f"{reader_role}: {error}")
        await s.execute(text("DELETE FROM data_requests WHERE org_id = :org AND id <> :req"), params)
        await s.execute(text("DELETE FROM orgs WHERE id = :org"), params)
        for table in org_tables:  # rows of tables without a cascading foreign key
            if table != "data_requests":
                await s.execute(text(f"DELETE FROM public.{q(table)} WHERE org_id = :org"), params)
        await audit.record(
            s,
            action="org.deleted",
            org_id=None,
            entity_type="org",
            entity_id=org_id,
            diff={**snapshot, "request_id": str(req.id), "rows": sum(before.values())},
        )
    try:
        await get_redis().delete(f"replay:org:{org_id}")
    except Exception as exc:  # cache only; never blocks the deletion
        log.warning("gdpr.redis_cleanup_failed", error=str(exc))

    checks = [
        _Check(f"table:{t}", f"SELECT count(*) FROM public.{q(t)} WHERE org_id = :org", {"org": org_id})
        for t in org_tables
        if t != "data_requests"
    ]
    checks.append(
        _Check("data_requests:other", "SELECT count(*) FROM data_requests WHERE org_id = :org", {"org": org_id})
    )
    checks.append(_Check("orgs", "SELECT count(*) FROM orgs WHERE id = :org", {"org": org_id}))
    for kb_id, schema_name, reader_role in kbs:
        if schema_name:
            checks.append(
                _Check(
                    f"schema:{schema_name}", "SELECT count(*) FROM pg_namespace WHERE nspname = :n", {"n": schema_name}
                )
            )
        if reader_role:
            checks.append(
                _Check(f"role:{reader_role}", "SELECT count(*) FROM pg_roles WHERE rolname = :r", {"r": reader_role})
            )
        checks.append(
            _Check(
                f"indexes:{kb_id}",
                "SELECT count(*) FROM pg_indexes WHERE schemaname = 'public' AND indexdef LIKE :p",
                {"p": f"%{kb_id}%"},
            )
        )
    post_checks = await _run_checks(checks)
    remaining_objects = [k for k in dict.fromkeys(keys) if await storage.exists(k)]
    post_checks.append(
        {
            "check": "storage:objects",
            "sql": "storage.exists(key) for each stored object",
            "remaining": len(remaining_objects),
        }
    )
    post_checks.append(
        {
            "check": "storage:prefix",
            "sql": f"storage prefix {org_id}/",
            "remaining": 1 if storage_purge.get("prefix_exists") else 0,
        }
    )
    post_checks.append(
        {
            "check": "repositories",
            "sql": "path.exists() for each project repository",
            "remaining": sum(1 for p in repo_paths if p.exists()),
        }
    )
    async with system_session() as s:
        retained_accounts = await _count(
            s,
            "SELECT count(*) FROM users u WHERE u.id = ANY(:ids) AND NOT EXISTS (SELECT 1 FROM memberships m WHERE m.user_id = u.id)",
            {"ids": member_ids or [uuid.uuid4()]},
        )
    return {
        "organization": snapshot,
        "deleted": {k: v for k, v in before.items() if v},
        "storage": {"objects": len(dict.fromkeys(keys)), "errors": storage_errors, **storage_purge},
        "knowledge_bases": len(kbs),
        "repositories": len(repo_paths),
        "stripe": stripe_result,
        "role_errors": role_errors,
        "member_accounts_without_org": retained_accounts,
        "post_checks": post_checks,
        "verified": all(c["remaining"] == 0 for c in post_checks),
    }


async def run_delete(request_id: uuid.UUID) -> DataRequest | None:
    req = await _claim(request_id, "delete")
    if req is None:
        return None
    try:
        report = await (_delete_org(req) if req.scope == "org" else _delete_user(req))
    except DataRequestError as exc:
        return await _fail(req, exc)
    except Exception as exc:
        log.exception("gdpr.delete_failed", request_id=str(request_id))
        return await _fail(req, exc)
    notify_email = report.pop("_notify_email", None)
    async with system_session() as s:
        row = await s.get(DataRequest, request_id)
        assert row is not None
        row.status = "completed" if report.get("verified") else "failed"
        row.completed_at = datetime.now(UTC)
        row.report = {**(row.report or {}), "deletion": report}
        await audit.record(
            s,
            action="data_request.delete_completed" if report.get("verified") else "data_request.delete_unverified",
            org_id=row.org_id,
            entity_type="data_request",
            entity_id=row.id,
            diff={"scope": row.scope, "verified": report.get("verified")},
        )
        requester = await s.get(User, row.user_id) if row.user_id else None
        recipient = requester.email if requester is not None and requester.deleted_at is None else notify_email
        locale = requester.locale if requester is not None else "es"
        summary = report.get("organization", {}).get("name") if row.scope == "org" else "cuenta / account"
    if recipient:
        try:
            await send_template(
                recipient,
                "data_delete_completed",
                {"subject": summary or "", "request_id": str(request_id)},
                locale,
            )
        except Exception as exc:
            log.warning("gdpr.delete_email_failed", request_id=str(request_id), error=str(exc))
    return row


# ============================================================================= lifecycle helpers


async def _claim(request_id: uuid.UUID, kind: str) -> DataRequest | None:
    async with system_session() as s:
        row = (
            await s.execute(select(DataRequest).where(DataRequest.id == request_id).with_for_update(skip_locked=True))
        ).scalar_one_or_none()
        if row is None or row.kind != kind or row.status not in ("pending", "failed"):
            return None
        row.status = "running"
        row.report = {**(row.report or {}), "started_at": datetime.now(UTC).isoformat()}
        await s.flush()
        s.expunge(row)
        return row


async def _fail(req: DataRequest, exc: Exception) -> DataRequest | None:
    code = exc.code if isinstance(exc, DataRequestError) else type(exc).__name__
    message = exc.message if isinstance(exc, DataRequestError) else str(exc)[:500]
    async with system_session() as s:
        row = await s.get(DataRequest, req.id)
        if row is None:
            return None
        row.status = "failed"
        row.report = {**(row.report or {}), "error": {"code": code, "message": message}}
        if row.kind == "delete" and row.scope == "org" and row.org_id is not None:
            org = await s.get(Org, row.org_id)
            if org is not None and org.blocked_reason == "Eliminación de la organización en curso":
                org.blocked_reason = "La eliminación falló; reinténtala desde el backoffice"
        await audit.record(
            s,
            action=f"data_request.{row.kind}_failed",
            org_id=row.org_id,
            entity_type="data_request",
            entity_id=row.id,
            diff={"code": code, "message": message},
        )
        return row


async def membership_role(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> str | None:
    return (
        await session.execute(select(Membership.role).where(Membership.org_id == org_id, Membership.user_id == user_id))
    ).scalar_one_or_none()


def zip_entries(data: bytes) -> list[str]:
    """Names inside an export archive (used by tests and the admin UI)."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return zf.namelist()
