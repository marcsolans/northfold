# Added by Messer: standalone platform for exported projects (see NOTICE).
"""Standalone Messer platform for exported projects: ``python -m messer.platform.standalone``.

An exported project's workforce members (``python -m messer.server``) point ``MESSER_API_HOST`` at this service,
which implements locally what the engine asks the Messer platform for: tracing, the model proxy, knowledge search
and read-only SQL over the exported knowledge bases, email and files. See :mod:`.app`.
"""

from typing import Any

from .config import StandaloneConfig

__all__ = ["StandaloneConfig", "create_app"]


def create_app(*args: Any, **kwargs: Any) -> Any:
    """Lazy re-export of :func:`.app.create_app` (FastAPI is part of the optional ``server`` extra)."""
    from .app import create_app as _create_app

    return _create_app(*args, **kwargs)
