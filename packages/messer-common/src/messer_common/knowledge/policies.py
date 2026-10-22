"""Per-role data policies for knowledge bases: row filters and column masking.

A policy (``kb_policies``) targets one table of the knowledge base, or ``*documents*`` for documents and
chunks, and one role: an organization role (``viewer``, ``builder``, ``admin``, ``owner``), ``agent``
(agents and API keys) or ``*`` (everyone). Masks: ``redact``, ``hash`` (16 hex chars of SHA-256, stable so
joins still work) and ``truncate:N``. Several policies for the same table combine: row filters are ANDed
and, per column, the most restrictive mask wins (redact > hash > truncate, shorter truncation first).

Governance modes (``knowledge_bases.governance_mode``):

* ``off``     — policies are ignored.
* ``shadow``  — nothing is masked; the result reports (and logs) what would have been filtered/masked.
* ``enforce`` — policies are applied.

Break-glass: an admin may bypass policies marked ``break_glass`` by giving a reason; the control plane
audits it. Policies without ``break_glass`` always apply.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import KbPolicy
from .errors import PolicyError
from .sqlcheck import quote_ident

DOCUMENTS_TABLE = "*documents*"
DOCUMENT_VIEWS = ("documents", "chunks")
POLICY_ROLES = ("viewer", "builder", "admin", "owner", "agent", "*")
GOVERNANCE_MODES = ("off", "shadow", "enforce")
REDACTED = "***"
_TRUNCATE_RE = re.compile(r"^truncate:(\d{1,4})$")


def parse_mask(mode: str) -> tuple[str, int]:
    """("redact"|"hash"|"truncate", n). Raises PolicyError for unknown modes."""
    value = mode.strip().lower()
    if value in ("redact", "hash"):
        return value, 0
    match = _TRUNCATE_RE.match(value)
    if match and 1 <= int(match.group(1)) <= 1000:
        return "truncate", int(match.group(1))
    raise PolicyError(f"Máscara no válida: {mode}. Usa redact, hash o truncate:N", details={"mask": mode})


def _restrictiveness(mode: str) -> tuple[int, int]:
    kind, n = parse_mask(mode)
    if kind == "redact":
        return (3, 0)
    if kind == "hash":
        return (2, 0)
    return (1, -n)


def stricter(a: str, b: str) -> str:
    return a if _restrictiveness(a) >= _restrictiveness(b) else b


def hash_value(value: Any) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def mask_value(value: Any, mode: str) -> Any:
    """Python masking, identical to :func:`mask_sql` for text values."""
    if value is None:
        return None
    kind, n = parse_mask(mode)
    if kind == "redact":
        return REDACTED
    if kind == "hash":
        return hash_value(value)
    return str(value)[:n]


def mask_sql(column: str, mode: str) -> str:
    """SQL expression masking ``column`` (always text-typed output)."""
    kind, n = parse_mask(mode)
    col = quote_ident(column)
    if kind == "redact":
        return f"CASE WHEN {col} IS NULL THEN NULL ELSE '{REDACTED}' END"
    if kind == "hash":
        return f"CASE WHEN {col} IS NULL THEN NULL ELSE left(encode(sha256(convert_to({col}::text, 'UTF8')), 'hex'), 16) END"
    return f"left({col}::text, {n})"


@dataclass(slots=True)
class PolicyRule:
    id: uuid.UUID
    table: str
    role: str
    row_filter: str | None
    masks: dict[str, str]
    compliance_tags: list[str]
    break_glass: bool


@dataclass(slots=True)
class EffectivePolicy:
    """Combined policies for one table."""

    table: str
    row_filters: list[str] = field(default_factory=list)
    masks: dict[str, str] = field(default_factory=dict)
    compliance_tags: list[str] = field(default_factory=list)
    policy_ids: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.row_filters and not self.masks

    def describe(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "row_filters": list(self.row_filters),
            "masked_columns": dict(self.masks),
            "compliance_tags": list(self.compliance_tags),
            "policy_ids": list(self.policy_ids),
        }


def policy_role(role: str | None) -> str:
    """Role whose policies apply: organization role, or ``agent`` for agents and API keys (None)."""
    return role if role in ("viewer", "builder", "admin", "owner") else "agent"


async def load_rules(session: AsyncSession, kb_id: uuid.UUID, role: str | None) -> list[PolicyRule]:
    target = policy_role(role)
    rows = (
        await session.execute(
            select(KbPolicy).where(
                KbPolicy.kb_id == kb_id, KbPolicy.enabled.is_(True), KbPolicy.role.in_([target, "*"])
            )
        )
    ).scalars()
    rules: list[PolicyRule] = []
    for p in rows:
        rules.append(
            PolicyRule(
                id=p.id,
                table=p.table,
                role=p.role,
                row_filter=(p.row_filter_sql or "").strip() or None,
                masks={str(k): str(v) for k, v in (p.masked_columns or {}).items()},
                compliance_tags=[str(t) for t in (p.compliance_tags or [])],
                break_glass=bool(p.break_glass),
            )
        )
    return rules


def combine(rules: list[PolicyRule], *, break_glass: bool = False) -> dict[str, EffectivePolicy]:
    """Effective policy per table; with ``break_glass`` the policies that allow it are skipped."""
    out: dict[str, EffectivePolicy] = {}
    for rule in rules:
        if break_glass and rule.break_glass:
            continue
        eff = out.setdefault(rule.table, EffectivePolicy(table=rule.table))
        if rule.row_filter:
            eff.row_filters.append(rule.row_filter)
        for column, mode in rule.masks.items():
            eff.masks[column] = stricter(eff.masks[column], mode) if column in eff.masks else mode
        for tag in rule.compliance_tags:
            if tag not in eff.compliance_tags:
                eff.compliance_tags.append(tag)
        eff.policy_ids.append(str(rule.id))
    return {k: v for k, v in out.items() if not v.empty}


def relation_policies(effective: dict[str, EffectivePolicy]) -> dict[str, EffectivePolicy]:
    """Map relation names (tables and the documents/chunks views) to their effective policy."""
    out: dict[str, EffectivePolicy] = {}
    for table, eff in effective.items():
        if table == DOCUMENTS_TABLE:
            for view in DOCUMENT_VIEWS:
                out[view] = eff
        else:
            out[table] = eff
    return out


def cte_sql(schema: str, relation: str, columns: list[str], eff: EffectivePolicy) -> str:
    """``"relation" AS (SELECT <masked columns> FROM "schema"."relation" WHERE <filters>)``."""
    select_list = ", ".join(
        f"{mask_sql(c, eff.masks[c])} AS {quote_ident(c)}" if c in eff.masks else quote_ident(c) for c in columns
    )
    where = " AND ".join(f"({f})" for f in eff.row_filters) or "true"
    return (
        f"{quote_ident(relation)} AS (SELECT {select_list} FROM {quote_ident(schema)}.{quote_ident(relation)} "
        f"WHERE {where})"
    )


@dataclass(slots=True)
class PolicyReport:
    mode: str
    role: str
    break_glass: bool = False
    applied: list[dict[str, Any]] = field(default_factory=list)
    would_apply: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "role": self.role,
            "break_glass": self.break_glass,
            "applied": self.applied,
            "would_apply": self.would_apply,
        }


def mask_hit_fields(hit: dict[str, Any], eff: EffectivePolicy) -> dict[str, Any]:
    """Mask search hit fields (content, heading, filename, metadata keys ``metadata.<key>``)."""
    out = dict(hit)
    for column, mode in eff.masks.items():
        if column in ("content", "heading", "filename") and out.get(column) is not None:
            out[column] = mask_value(out[column], mode)
        elif column == "metadata" and out.get("metadata"):
            out["metadata"] = {k: mask_value(v, mode) for k, v in dict(out["metadata"]).items()}
        elif column.startswith("metadata.") and isinstance(out.get("metadata"), dict):
            key = column.split(".", 1)[1]
            meta = dict(out["metadata"])
            if key in meta:
                meta[key] = mask_value(meta[key], mode)
            out["metadata"] = meta
    return out
