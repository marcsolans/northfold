"""Connector catalog: seeded into the ``connectors`` table from ``messer_connectors`` and served to the UI."""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db.models import Connector
from messer_common.logging import get_logger
from messer_connectors import oauth, registry
from messer_connectors.base import ConnectorAdapter, ConnectorSpec

log = get_logger("messer.connectors.catalog")


def capabilities_json(spec: ConnectorSpec) -> dict[str, Any]:
    data = spec.capabilities.model_dump()
    data["description_en"] = spec.description_en
    data["event_specs"] = [e.model_dump() for e in spec.events]
    if spec.oauth is not None:
        data["oauth"] = {
            "authorize_url": spec.oauth.authorize_url,
            "token_url": spec.oauth.token_url,
            "scopes": spec.oauth.scopes,
        }
    return data


async def seed_connectors(session: AsyncSession) -> None:
    """Upsert every registered connector (idempotent; keeps rows referenced by connections)."""
    count = 0
    for spec in registry.catalog():
        values = {
            "key": spec.key,
            "name": spec.name,
            "category": spec.category,
            "auth_type": spec.auth_type,
            "description": spec.description,
            "capabilities": capabilities_json(spec),
            "icon": spec.icon,
        }
        await session.execute(
            insert(Connector)
            .values(**values)
            .on_conflict_do_update(index_elements=[Connector.key], set_={k: v for k, v in values.items() if k != "key"})
        )
        count += 1
    log.info("connectors.seeded", count=count)


def availability(spec: ConnectorSpec) -> dict[str, Any]:
    """Whether "Conectar" runs the real OAuth flow or creates a demo connection, and what is missing."""
    if spec.auth_type != "oauth2":
        return {"mode": "live", "missing_env": []}
    missing = oauth.missing_env(spec)
    return {"mode": "demo" if missing else "oauth", "missing_env": missing}


def connector_out(adapter: ConnectorAdapter) -> dict[str, Any]:
    spec = adapter.spec
    return {
        "key": spec.key,
        "name": spec.name,
        "category": spec.category,
        "auth_type": spec.auth_type,
        "description": spec.description,
        "description_en": spec.description_en,
        "icon": spec.icon,
        "capabilities": spec.capabilities.model_dump(),
        "events": [e.model_dump() for e in spec.events],
        "config_fields": [f.model_dump() for f in spec.config_fields],
        "docs_url": spec.docs_url,
        "oauth": (
            {"provider": spec.oauth.provider, "scopes": [*spec.oauth.scopes, *spec.oauth.user_scopes]}
            if spec.oauth is not None
            else None
        ),
        "availability": availability(spec),
    }


def search(query: str | None = None, category: str | None = None) -> list[dict[str, Any]]:
    terms = [t for t in (query or "").lower().split() if t]
    out: list[dict[str, Any]] = []
    for adapter in registry.adapters():
        spec = adapter.spec
        if category and spec.category != category:
            continue
        haystack = " ".join(
            [spec.key, spec.name, spec.description, spec.description_en, spec.category, *spec.capabilities.actions]
        ).lower()
        if terms and not all(t in haystack for t in terms):
            continue
        out.append(connector_out(adapter))
    return out
