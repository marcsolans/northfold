"""Job discovery: every module in ``messer_worker.jobs`` exposing ``JOBS`` (a list of async functions
``async def job(ctx, *args, **kwargs)``) is registered. Function names are the job names used by
``messer_common.queue.enqueue`` (see ``messer_common.queue.Jobs``)."""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from typing import Any

from . import jobs as jobs_pkg


def discover_jobs() -> list[Callable[..., Any]]:
    found: list[Callable[..., Any]] = []
    seen: set[str] = set()
    for info in sorted(pkgutil.iter_modules(jobs_pkg.__path__), key=lambda m: m.name):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{jobs_pkg.__name__}.{info.name}")
        for fn in getattr(module, "JOBS", []):
            if fn.__name__ in seen:
                raise RuntimeError(f"duplicate job name {fn.__name__} in {module.__name__}")
            seen.add(fn.__name__)
            found.append(fn)
    return found
