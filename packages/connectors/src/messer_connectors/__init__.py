"""Messer connectors: catalog, adapters, OAuth, credentials, syncs and events (contracts §4).

Public entry points::

    from messer_connectors import registry, credentials
    adapter = registry.get_adapter("gmail")
    ctx = await credentials.load_context(session, connection_id)
    result = await adapter.run_action(ctx, "search_messages", {"query": "factura"})

The package root imports nothing heavy so that ``messer_connectors.sql`` can be bundled alone into the
on-prem connector agent.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "1.0.0"
