"""/api/v1/model-policy — which models the organization may use (§7.11 model policy).

Rules are glob patterns over ``provider/model`` ids: ``deny`` always wins; when ``allow`` is not empty only
matching models are allowed. The runtime model gateway enforces them on every call
(``messer_runtime.gateway._policy_allows``) — saving a policy invalidates the gateway caches. Patterns are
validated against the models Messer knows (``config/models.yaml`` and the model price table), and a policy
that would block every model is refused. Members read; admins change it (audited).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit, runtime_client
from messer_common.db import Principal
from messer_common.db.models import ModelPolicy

from ..deps import get_db, require_role
from ..errors import ApiError, Conflict
from ..services.analytics import known_models, normalize_patterns, preview_policy, validate_policy

router = APIRouter(prefix="/model-policy", tags=["model-policy"])

Pattern = str


class RulesIn(BaseModel):
    allow: list[Pattern] = Field(default_factory=list, max_length=100)
    deny: list[Pattern] = Field(default_factory=list, max_length=100)

    def normalized(self) -> dict[str, list[str]]:
        return {
            "allow": normalize_patterns(p[:200] for p in self.allow),
            "deny": normalize_patterns(p[:200] for p in self.deny),
        }


class RulesOut(BaseModel):
    allow: list[str]
    deny: list[str]


class PolicyModelOut(BaseModel):
    model: str
    display_name: str
    provider: str
    tiers: list[str]
    roles: list[str]
    allowed: bool
    reason: str
    pattern: str | None


class PolicyIssue(BaseModel):
    field: str | None = None
    pattern: str | None = None
    code: str
    message: str | None = None
    tier: str | None = None
    role: str | None = None
    model: str | None = None


class PolicyOut(BaseModel):
    rules: RulesOut
    updated_at: datetime | None
    models: list[PolicyModelOut]
    allowed_count: int
    total: int
    warnings: list[PolicyIssue]
    errors: list[PolicyIssue] = Field(default_factory=list)


def _rules_of(policy: ModelPolicy | None) -> dict[str, list[str]]:
    rules: dict[str, Any] = dict(policy.rules or {}) if policy is not None else {}
    return {
        "allow": [str(p) for p in rules.get("allow", []) or []],
        "deny": [str(p) for p in rules.get("deny", []) or []],
    }


async def _current(session: AsyncSession, principal: Principal) -> ModelPolicy | None:
    return (
        await session.execute(select(ModelPolicy).where(ModelPolicy.org_id == principal.org_id))
    ).scalar_one_or_none()


async def _build(
    session: AsyncSession, rules: dict[str, list[str]], updated_at: datetime | None, errors: list[dict[str, Any]]
) -> PolicyOut:
    known = await known_models(session)
    preview = preview_policy(dict(rules), known)
    return PolicyOut(
        rules=RulesOut(allow=rules["allow"], deny=rules["deny"]),
        updated_at=updated_at,
        models=[PolicyModelOut(**m) for m in preview["models"]],
        allowed_count=preview["allowed_count"],
        total=preview["total"],
        warnings=[PolicyIssue(**w) for w in preview["warnings"]],
        errors=[PolicyIssue(**e) for e in errors],
    )


@router.get("", response_model=PolicyOut)
async def get_policy(
    principal: Principal = Depends(require_role("viewer")), db: AsyncSession = Depends(get_db)
) -> PolicyOut:
    policy = await _current(db, principal)
    return await _build(db, _rules_of(policy), policy.updated_at if policy else None, [])


@router.post("/preview", response_model=PolicyOut)
async def preview(
    body: RulesIn, principal: Principal = Depends(require_role("viewer")), db: AsyncSession = Depends(get_db)
) -> PolicyOut:
    """Which models a policy would allow, with validation errors (nothing is saved)."""
    rules = body.normalized()
    errors = validate_policy(rules, await known_models(db))
    policy = await _current(db, principal)
    return await _build(db, rules, policy.updated_at if policy else None, errors)


@router.put("", response_model=PolicyOut)
async def put_policy(
    body: RulesIn, principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> PolicyOut:
    assert principal.org_id is not None
    rules = body.normalized()
    errors = validate_policy(rules, await known_models(db))
    if errors:
        raise ApiError(
            "La política de modelos no es válida",
            code="invalid_model_policy",
            status_code=422,
            details={"errors": errors},
        )
    policy = await _current(db, principal)
    before = _rules_of(policy)
    if policy is None:
        policy = ModelPolicy(org_id=principal.org_id, rules=rules)
        db.add(policy)
    else:
        policy.rules = {**dict(policy.rules or {}), **rules}
    try:
        await db.flush()
    except IntegrityError as exc:
        raise Conflict("Otra persona ha guardado la política a la vez. Recarga y vuelve a intentarlo.") from exc
    await audit.record(
        db,
        action="model_policy.updated",
        principal=principal,
        entity_type="model_policy",
        entity_id=policy.id,
        diff={"before": before, "after": rules},
    )
    await db.refresh(policy)
    out = await _build(db, rules, policy.updated_at, [])
    # The gateway caches organization info for a few seconds; push the change now (best effort).
    await runtime_client.invalidate_caches()
    return out
