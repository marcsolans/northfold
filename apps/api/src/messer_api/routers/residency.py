"""/api/v1/residency — data residency mode, EU region, provider compliance and retention of the organization.

Changes are made through ``PATCH /api/v1/orgs/current`` (``data_residency``, ``region``,
``trace_retention_days``, ``conversation_retention_days``); this endpoint explains the current state.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db import Principal
from messer_common.db.models import AuditLog, Org
from messer_common.models_config import bedrock_allowed_regions, bedrock_region, load_models_config
from messer_common.residency import (
    EU_REGIONS,
    Residency,
    allowed_provider,
    deployment_providers,
    model_route,
    org_residency,
)
from messer_common.settings import get_settings

from ..deps import get_db, require_role
from ..errors import NotFound
from ..services import limits
from ..services.sso import org_has_feature

router = APIRouter(prefix="/residency", tags=["residency"])


@router.get("")
async def residency_overview(
    principal: Principal = Depends(require_role("viewer")), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    assert principal.org_id is not None
    org = await db.get(Org, principal.org_id)
    if org is None:
        raise NotFound("Organización no encontrada")
    settings = get_settings()
    current = await org_residency(db, org.id)
    strict = Residency(org_id=org.id, mode="eu_strict", region=current.region)
    providers = [
        {
            "kind": kind,
            "provider": provider,
            "region": region,
            "allowed_in_eu_strict": allowed_provider(strict, kind, provider, region=region),
            "active": allowed_provider(current, kind, provider, region=region),
        }
        for kind, provider, region in deployment_providers()
    ]
    upgrade = await limits.cheapest_plan_with_feature(db, "eu_strict")
    last_purge = (
        await db.execute(
            select(AuditLog.created_at, AuditLog.diff)
            .where(AuditLog.org_id == org.id, AuditLog.action == "retention.purged")
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
    ).first()
    bedrock_models = load_models_config().get("bedrock", {}).get("models", {}) or {}
    return {
        "data_residency": current.mode,
        "region": current.region,
        "regions": [{"id": rid, "name": name} for rid, name in EU_REGIONS.items()],
        "model_route": model_route(current),
        "eu_strict_available": await org_has_feature(db, org.id, "eu_strict"),
        "eu_strict_upgrade_to": upgrade.id if upgrade else None,
        "bedrock": {
            "configured": settings.has_bedrock,
            "region": settings.aws_region or bedrock_region(),
            "allowed_regions": bedrock_allowed_regions(),
            "models": [{"model": model, "bedrock_id": bid} for model, bid in bedrock_models.items()],
        },
        "providers": providers,
        "retention": {
            "trace_days": org.trace_retention_days,
            "conversation_days": org.conversation_retention_days,
            "last_purge_at": last_purge[0].isoformat() if last_purge else None,
            "last_purge": last_purge[1] if last_purge else None,
        },
    }
