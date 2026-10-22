"""Metric catalog for alarms: built-in run metrics and ``custom:<id>`` metrics, evaluated over a window."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import CustomMetric
from .custom_metrics import metric_value as custom_value
from .custom_metrics import parse_definition
from .filters import Filters
from .queries import feedback_stats, kpis


@dataclass(frozen=True, slots=True)
class BuiltinMetric:
    key: str
    unit: str  # count | percent | ms | usd | credits
    label_es: str
    label_en: str

    def label(self, locale: str) -> str:
        return self.label_en if locale == "en" else self.label_es


BUILTIN_METRICS: dict[str, BuiltinMetric] = {
    m.key: m
    for m in (
        BuiltinMetric("runs", "count", "Ejecuciones", "Runs"),
        BuiltinMetric("errors", "count", "Ejecuciones con error", "Failed runs"),
        BuiltinMetric("error_rate", "percent", "Tasa de error", "Error rate"),
        BuiltinMetric("success_rate", "percent", "Tasa de éxito", "Success rate"),
        BuiltinMetric("latency_p50_ms", "ms", "Latencia p50", "p50 latency"),
        BuiltinMetric("latency_p95_ms", "ms", "Latencia p95", "p95 latency"),
        BuiltinMetric("cost_usd", "usd", "Coste", "Cost"),
        BuiltinMetric("credits", "credits", "Créditos consumidos", "Credits used"),
        BuiltinMetric("users", "count", "Usuarios", "Users"),
        BuiltinMetric("feedback_negative_rate", "percent", "Valoraciones negativas", "Negative feedback"),
    )
}

CUSTOM_PREFIX = "custom:"


class UnknownMetric(LookupError):
    pass


def custom_metric_id(metric: str) -> uuid.UUID | None:
    if not metric.startswith(CUSTOM_PREFIX):
        return None
    try:
        return uuid.UUID(metric[len(CUSTOM_PREFIX) :])
    except ValueError as exc:
        raise UnknownMetric(metric) from exc


def _pct(value: float | None) -> float | None:
    return round(value * 100, 4) if value is not None else None


async def builtin_value(session: AsyncSession, metric: str, f: Filters) -> float | None:
    """Value of a built-in metric over ``f`` (rates in percent, ``None`` when undefined, e.g. no runs)."""
    if metric not in BUILTIN_METRICS:
        raise UnknownMetric(metric)
    if metric == "feedback_negative_rate":
        stats = await feedback_stats(session, f)
        return _pct(stats.down / stats.total) if stats.total else None
    k = await kpis(session, f)
    values: dict[str, float | None] = {
        "runs": float(k.runs),
        "errors": float(k.errors),
        "error_rate": _pct(k.error_rate),
        "success_rate": _pct(k.success_rate),
        "latency_p50_ms": k.p50_ms,
        "latency_p95_ms": k.p95_ms,
        "cost_usd": float(k.cost_usd),
        "credits": float(k.credits),
        "users": float(k.users),
    }
    return values[metric]


async def metric_value(session: AsyncSession, metric: str, f: Filters) -> float | None:
    """Built-in metric name or ``custom:<uuid>`` of a custom metric of ``f.org_id``."""
    metric_id = custom_metric_id(metric)
    if metric_id is None:
        return await builtin_value(session, metric, f)
    row = await session.get(CustomMetric, metric_id)
    if row is None or row.org_id != f.org_id:
        raise UnknownMetric(metric)
    return await custom_value(session, parse_definition(row.definition or {}), f)


def metric_unit(metric: str, custom: CustomMetric | None = None) -> str:
    if metric in BUILTIN_METRICS:
        return BUILTIN_METRICS[metric].unit
    if custom is not None:
        try:
            return parse_definition(custom.definition or {}).unit
        except ValueError:
            return "count"
    return "count"
