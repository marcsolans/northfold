"""Routers are auto-discovered: every module here exposing ``router`` is mounted under /api/v1,
and every module exposing ``public_router`` is mounted at the root (public API, webhooks, hooks)."""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType


def discover() -> list[ModuleType]:
    modules: list[ModuleType] = []
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        if info.name.startswith("_"):
            continue
        modules.append(importlib.import_module(f"{__name__}.{info.name}"))
    return modules
