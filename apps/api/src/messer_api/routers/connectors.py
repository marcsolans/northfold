"""/api/v1/connectors — connector catalog (searchable, by category)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from messer_common.db import Principal
from messer_connectors import registry

from ..deps import get_org_principal
from ..services import connectors_catalog
from ..services.connections import adapter_for

router = APIRouter(prefix="/connectors", tags=["connectors"])


@router.get("")
async def list_connectors(
    q: str | None = Query(default=None, max_length=200),
    category: str | None = Query(default=None, max_length=60),
    _: Principal = Depends(get_org_principal),
) -> dict[str, Any]:
    items = connectors_catalog.search(q, category)
    counts: dict[str, int] = {}
    for adapter in registry.adapters():
        counts[adapter.spec.category] = counts.get(adapter.spec.category, 0) + 1
    categories = [{"key": c, "count": counts.get(c, 0)} for c in registry.CATEGORIES if counts.get(c)]
    return {"items": items, "categories": categories}


@router.get("/{key}")
async def get_connector(key: str, _: Principal = Depends(get_org_principal)) -> dict[str, Any]:
    adapter = adapter_for(key)
    out = connectors_catalog.connector_out(adapter)
    out["actions"] = [a.model_dump() for a in adapter.actions()]
    return out
