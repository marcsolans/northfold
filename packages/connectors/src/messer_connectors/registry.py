"""Connector registry: ``get_adapter(key)`` and ``catalog()`` (contracts §4).

Adapter modules are imported lazily on first use so importing the registry stays cheap.
"""

from __future__ import annotations

import importlib
import threading

from .base import ConnectorAdapter, ConnectorError, ConnectorSpec

ADAPTER_MODULES = [
    "messer_connectors.adapters.google",
    "messer_connectors.adapters.microsoft",
    "messer_connectors.adapters.slack",
    "messer_connectors.adapters.notion",
    "messer_connectors.adapters.hubspot",
    "messer_connectors.adapters.salesforce",
    "messer_connectors.adapters.databases",
    "messer_connectors.adapters.webhooks",
    "messer_connectors.adapters.http_generic",
    "messer_connectors.adapters.mcp",
    "messer_connectors.adapters.onprem_files",
]

CATEGORIES = ["files", "communication", "productivity", "crm", "database", "developer"]

_adapters: dict[str, ConnectorAdapter] = {}
_loaded = False
_lock = threading.Lock()


class UnknownConnector(ConnectorError):
    code = "unknown_connector"
    status_code = 404


def register(adapter_cls: type[ConnectorAdapter]) -> type[ConnectorAdapter]:
    """Class decorator: register an adapter under ``adapter_cls.spec.key``."""
    key = adapter_cls.spec.key
    existing = _adapters.get(key)
    if existing is not None and type(existing) is not adapter_cls:
        raise RuntimeError(f"duplicate connector key {key}")
    _adapters[key] = adapter_cls()
    return adapter_cls


def _load() -> None:
    global _loaded
    if _loaded:
        return
    with _lock:
        if _loaded:
            return
        for module in ADAPTER_MODULES:
            importlib.import_module(module)
        _loaded = True


def get_adapter(key: str) -> ConnectorAdapter:
    _load()
    adapter = _adapters.get(key)
    if adapter is None:
        raise UnknownConnector(f"Conector desconocido: {key}", details={"key": key})
    return adapter


def adapters() -> list[ConnectorAdapter]:
    _load()
    order = {c: i for i, c in enumerate(CATEGORIES)}
    return sorted(_adapters.values(), key=lambda a: (order.get(a.spec.category, 99), a.spec.name.lower()))


def catalog() -> list[ConnectorSpec]:
    return [a.spec for a in adapters()]
