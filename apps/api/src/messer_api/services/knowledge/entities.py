"""Basic entity resolution across a knowledge base's tables.

1. Deterministic keys: tax ids (Spanish NIF/NIE/CIF and EU VAT numbers, normalized without separators or
   country prefix), e-mail addresses and web domains. Records sharing a key form a group.
2. Similarity: names (company/person name columns) normalized (accents, punctuation and legal suffixes such
   as S.L., S.A., Inc. removed) and compared with ``pg_trgm`` similarity.

Groups become ``kb_entities`` suggestions. A person merges a suggestion into a golden record (stored on the
entity, visible in the ``entities`` view, audited) or dismisses it.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db.models import KbEntity, KbTable, KnowledgeBase
from messer_common.knowledge.sql import jsonable
from messer_common.knowledge.sqlcheck import quote_ident
from messer_common.logging import get_logger

from .tables import table_columns, table_primary_key

log = get_logger("messer.api.knowledge.entities")

MAX_ROWS_PER_TABLE = 20_000
SIMILARITY_THRESHOLD = 0.6
MAX_GROUP = 25

_TAX_COLUMNS = re.compile(
    r"(^|_)(nif|cif|nie|dni|vat|vat_id|vat_number|tax_id|taxid|tax_number|tin|ein|ruc|rfc|cuit|siren|siret|ust_id|"
    r"partita_iva|codice_fiscale|btw|nif_cif|identificacion_fiscal)(_|$)"
)
_EMAIL_COLUMNS = re.compile(r"(^|_)(e_?mail|correo|mail|email_address|correo_electronico)(_|$)")
_DOMAIN_COLUMNS = re.compile(r"(^|_)(domain|dominio|website|web|url|sitio_web|homepage|pagina_web|site)(_|$)")
_NAME_COLUMNS = (
    "razon_social",
    "company_name",
    "company",
    "empresa",
    "nombre_empresa",
    "account_name",
    "account",
    "cliente",
    "customer",
    "customer_name",
    "proveedor",
    "supplier",
    "vendor",
    "organization",
    "organizacion",
    "full_name",
    "nombre_completo",
    "contact_name",
    "name",
    "nombre",
)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.IGNORECASE)
_NIF_RE = re.compile(r"^(\d{8}[A-Z]|[XYZ]\d{7}[A-Z]|[ABCDEFGHJKLMNPQRSUVW]\d{7}[0-9A-J])$")
_VAT_RE = re.compile(
    r"^(AT|BE|BG|CY|CZ|DE|DK|EE|EL|ES|FI|FR|HR|HU|IE|IT|LT|LU|LV|MT|NL|PL|PT|RO|SE|SI|SK|XI)[0-9A-Z]{8,12}$"
)
FREE_MAIL = frozenset(
    "gmail.com googlemail.com hotmail.com hotmail.es outlook.com outlook.es live.com yahoo.com yahoo.es icloud.com "
    "me.com msn.com aol.com protonmail.com proton.me gmx.com gmx.de web.de telefonica.net movistar.es".split()
)
LEGAL_SUFFIXES = frozenset(
    "sl slu sa sau sll scp sc scoop sociedad limitada anonima unipersonal inc incorporated ltd limited llc llp "
    "plc corp corporation co company gmbh ag kg bv nv srl spa sas sarl oy ab as aps".split()
)


def _strip_accents(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))


def normalize_tax_id(value: Any) -> str | None:
    raw = re.sub(r"[\s.\-/]", "", _strip_accents(str(value or ""))).upper()
    if not raw:
        return None
    if _VAT_RE.match(raw):
        country, number = raw[:2], raw[2:]
        return number if country == "ES" else f"{country}{number}"
    if _NIF_RE.match(raw):
        return raw
    return None


def normalize_email(value: Any) -> str | None:
    raw = str(value or "").strip().lower()
    if raw.startswith("mailto:"):
        raw = raw[7:]
    return raw if _EMAIL_RE.match(raw) else None


def normalize_domain(value: Any) -> str | None:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    if "@" in raw:
        raw = raw.rsplit("@", 1)[1]
    raw = re.sub(r"^[a-z]+://", "", raw)
    raw = raw.split("/", 1)[0].split("?", 1)[0].split(":", 1)[0]
    raw = raw.removeprefix("www.")
    if "." not in raw or not re.fullmatch(r"[a-z0-9.\-]+", raw) or raw in FREE_MAIL:
        return None
    return raw


def normalize_name(value: Any) -> str | None:
    raw = _strip_accents(str(value or "")).lower()
    raw = re.sub(r"[^a-z0-9 ]+", " ", raw.replace(".", ""))
    words = [w for w in raw.split() if w not in LEGAL_SUFFIXES]
    name = " ".join(words)
    return name if len(name) >= 3 else None


@dataclass(slots=True)
class _Record:
    table: str
    pk: dict[str, Any]
    values: dict[str, Any]
    keys: dict[str, str] = field(default_factory=dict)  # kind -> normalized value
    name: str | None = None

    def ref(self) -> dict[str, Any]:
        return {"table": self.table, "pk": self.pk, "values": self.values}


@dataclass(slots=True)
class _Classified:
    tax: list[str]
    email: list[str]
    domain: list[str]
    name: str | None


def _classify(columns: list[dict[str, Any]]) -> _Classified:
    names = [str(c["name"]) for c in columns]
    tax = [n for n in names if _TAX_COLUMNS.search(n)]
    email = [n for n in names if _EMAIL_COLUMNS.search(n)]
    domain = [n for n in names if _DOMAIN_COLUMNS.search(n) and n not in email]
    name = next((candidate for candidate in _NAME_COLUMNS if candidate in names), None)
    if name is None:
        name = next((n for n in names if n.endswith("_name") or n.startswith("nombre")), None)
    return _Classified(tax, email, domain, name)


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


async def _collect(session: AsyncSession, kb: KnowledgeBase) -> list[_Record]:
    tables = (await session.execute(select(KbTable).where(KbTable.kb_id == kb.id).order_by(KbTable.name))).scalars()
    records: list[_Record] = []
    for table in tables:
        columns = table_columns(table)
        classified = _classify(columns)
        if not (classified.tax or classified.email or classified.domain or classified.name):
            continue
        pk = table_primary_key(table)
        wanted = classified.tax + classified.email + classified.domain + ([classified.name] if classified.name else [])
        display = [c["name"] for c in columns[:8]]
        select_cols = list(dict.fromkeys(pk + wanted + display))
        rows = await session.execute(
            text(
                "SELECT "
                + ", ".join(quote_ident(c) for c in select_cols)
                + f" FROM {quote_ident(kb.schema_name)}.{quote_ident(table.name)} LIMIT {MAX_ROWS_PER_TABLE}"
            )
        )
        for row in rows.mappings():
            record = _Record(
                table=table.name,
                pk={k: jsonable(row[k]) for k in pk},
                values={k: jsonable(row[k]) for k in select_cols if k not in pk or k in display},
            )
            for column in classified.tax:
                key = normalize_tax_id(row[column])
                if key:
                    record.keys.setdefault("tax_id", key)
            for column in classified.email:
                key = normalize_email(row[column])
                if key:
                    record.keys.setdefault("email", key)
            for column in classified.domain:
                key = normalize_domain(row[column])
                if key:
                    record.keys.setdefault("domain", key)
            if classified.name:
                record.name = normalize_name(row[classified.name])
            if record.keys or record.name:
                records.append(record)
    return records


def _entity_type(records: list[_Record]) -> str:
    if any("tax_id" in r.keys or "domain" in r.keys for r in records):
        return "company"
    if all("email" in r.keys for r in records):
        return "person"
    return "generic"


async def _similar_pairs(session: AsyncSession, records: list[_Record]) -> list[tuple[int, int, float]]:
    named = [(i, r.name) for i, r in enumerate(records) if r.name]
    if len(named) < 2:
        return []
    await session.execute(text("DROP TABLE IF EXISTS pg_temp._messer_entity_names"))
    await session.execute(text("CREATE TEMP TABLE _messer_entity_names (idx int, name text) ON COMMIT DROP"))
    for start in range(0, len(named), 1000):
        await session.execute(
            text("INSERT INTO _messer_entity_names (idx, name) VALUES (:i, :n)"),
            [{"i": i, "n": n} for i, n in named[start : start + 1000]],
        )
    await session.execute(text("CREATE INDEX ON _messer_entity_names USING gin (name gin_trgm_ops)"))
    await session.execute(
        text("SELECT set_config('pg_trgm.similarity_threshold', :t, true)"), {"t": str(SIMILARITY_THRESHOLD)}
    )
    rows = await session.execute(
        text(
            "SELECT a.idx, b.idx, similarity(a.name, b.name) FROM _messer_entity_names a "
            "JOIN _messer_entity_names b ON a.idx < b.idx AND a.name % b.name "
            "WHERE similarity(a.name, b.name) >= :t ORDER BY 3 DESC LIMIT 50000"
        ),
        {"t": SIMILARITY_THRESHOLD},
    )
    pairs = [(int(a), int(b), float(score)) for a, b, score in rows]
    await session.execute(text("DROP TABLE IF EXISTS pg_temp._messer_entity_names"))
    return pairs


@dataclass(slots=True)
class Suggestion:
    match_key: str
    method: str
    score: float
    entity_type: str
    records: list[dict[str, Any]]


def _deterministic_groups(records: list[_Record]) -> tuple[list[Suggestion], _UnionFind]:
    uf = _UnionFind(len(records))
    first_key: dict[str, int] = {}
    for i, record in enumerate(records):
        for kind, value in record.keys.items():
            key = f"{kind}:{value}"
            if key in first_key:
                uf.union(first_key[key], i)
            else:
                first_key[key] = i
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(len(records)):
        groups[uf.find(i)].append(i)
    out: list[Suggestion] = []
    priority = ("tax_id", "email", "domain")
    for members in groups.values():
        if len(members) < 2:
            continue
        members = members[:MAX_GROUP]
        group = [records[i] for i in members]
        shared: str | None = None
        for kind in priority:
            values = [r.keys.get(kind) for r in group if r.keys.get(kind)]
            if len(values) >= 2 and len(set(values)) < len(values):
                shared = f"{kind}:{max(set(values), key=values.count)}"
                break
        if shared is None:
            kind = next(k for k in priority if any(k in r.keys for r in group))
            shared = f"{kind}:{next(r.keys[kind] for r in group if kind in r.keys)}"
        out.append(Suggestion(shared, "deterministic", 1.0, _entity_type(group), [r.ref() for r in group]))
    return out, uf


async def compute_suggestions(session: AsyncSession, kb: KnowledgeBase) -> list[Suggestion]:
    records = await _collect(session, kb)
    suggestions, deterministic = _deterministic_groups(records)
    pairs = await _similar_pairs(session, records)
    sim = _UnionFind(len(records))
    best: dict[int, float] = {}
    for a, b, score in pairs:
        if deterministic.find(a) == deterministic.find(b):
            continue  # already suggested by a deterministic key
        sim.union(a, b)
        best[a] = max(best.get(a, 0.0), score)
        best[b] = max(best.get(b, 0.0), score)
    clusters: dict[int, set[int]] = defaultdict(set)
    for a, b, _ in pairs:
        if deterministic.find(a) == deterministic.find(b):
            continue
        clusters[sim.find(a)].update((a, b))
    for cluster in clusters.values():
        if len(cluster) < 2:
            continue
        members = sorted(cluster)[:MAX_GROUP]
        group = [records[i] for i in members]
        score = round(max(best.get(i, 0.0) for i in members), 3)
        name = group[0].name or "?"
        suggestions.append(
            Suggestion(f"similar:{name}", "similarity", score, _entity_type(group), [r.ref() for r in group])
        )
    return suggestions


async def run_entity_resolution(session: AsyncSession, kb: KnowledgeBase) -> dict[str, int]:
    """Refresh suggestions (owner session). Decided entities (merged/dismissed) are kept untouched."""
    suggestions = await compute_suggestions(session, kb)
    existing = {
        e.match_key: e for e in (await session.execute(select(KbEntity).where(KbEntity.kb_id == kb.id))).scalars()
    }
    seen: set[str] = set()
    created = updated = 0
    for suggestion in suggestions:
        key = suggestion.match_key[:2000]
        if key in seen:
            continue
        seen.add(key)
        entity = existing.get(key)
        if entity is None:
            session.add(
                KbEntity(
                    org_id=kb.org_id,
                    kb_id=kb.id,
                    entity_type=suggestion.entity_type,
                    match_key=key,
                    method=suggestion.method,
                    score=suggestion.score,
                    records=suggestion.records,
                    status="suggested",
                )
            )
            created += 1
        elif entity.status == "suggested":
            entity.records = suggestion.records
            entity.score = suggestion.score
            entity.method = suggestion.method
            entity.entity_type = suggestion.entity_type
            updated += 1
    stale = 0
    for key, entity in existing.items():
        if entity.status == "suggested" and key not in seen:
            await session.delete(entity)
            stale += 1
    await session.flush()
    stats = {"suggestions": len(seen), "created": created, "updated": updated, "removed": stale}
    log.info("knowledge.entities", kb_id=str(kb.id), **stats)
    return stats


def default_golden_record(records: list[dict[str, Any]]) -> dict[str, Any]:
    """First non-empty value of every field, in record order."""
    golden: dict[str, Any] = {}
    for record in records:
        for key, value in (record.get("values") or {}).items():
            if key not in golden and value not in (None, ""):
                golden[key] = value
    return golden


def merge(entity: KbEntity, *, golden: dict[str, Any] | None, decided_by: uuid.UUID | None) -> KbEntity:
    records = list(entity.records or [])
    fields = golden if golden is not None else default_golden_record(records)
    entity.golden_record = {
        "fields": {str(k): jsonable(v) for k, v in fields.items()},
        "sources": [{"table": r.get("table"), "pk": r.get("pk")} for r in records],
    }
    entity.status = "merged"
    entity.decided_by = decided_by
    entity.decided_at = datetime.now(UTC)
    return entity


def dismiss(entity: KbEntity, *, decided_by: uuid.UUID | None) -> KbEntity:
    entity.status = "dismissed"
    entity.decided_by = decided_by
    entity.decided_at = datetime.now(UTC)
    return entity
