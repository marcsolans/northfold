"""AI analytics shared by the API (dashboards, CSV) and the alarm evaluator (scheduler).

* :mod:`.filters` — :class:`Filters` (org, window, project/environment/channel/agent), buckets, time zones.
* :mod:`.queries` — KPIs, time series, breakdowns, model usage and feedback.
* :mod:`.custom_metrics` — metrics defined over traces, compiled to parameterized SQL.
* :mod:`.metrics` — metric catalog for alarms (built-in names and ``custom:<id>``).
"""

from .custom_metrics import MetricDefinition, MetricFilter, MetricSeries, metric_series, parse_definition
from .filters import (
    BUCKETS,
    FAILED_STATUSES,
    TERMINAL_STATUSES,
    AnalyticsError,
    Bucket,
    Filters,
    auto_bucket,
)
from .metrics import BUILTIN_METRICS, CUSTOM_PREFIX, BuiltinMetric, UnknownMetric, custom_metric_id, metric_value
from .queries import (
    GROUP_BYS,
    SORT_KEYS,
    BreakdownRow,
    FeedbackComment,
    FeedbackStats,
    GroupBy,
    Kpis,
    ModelUsage,
    Point,
    SortKey,
    breakdown,
    feedback_comments,
    feedback_stats,
    kpis,
    model_usage,
    timeseries,
)

__all__ = [
    "BUCKETS",
    "BUILTIN_METRICS",
    "CUSTOM_PREFIX",
    "FAILED_STATUSES",
    "GROUP_BYS",
    "SORT_KEYS",
    "TERMINAL_STATUSES",
    "AnalyticsError",
    "BreakdownRow",
    "Bucket",
    "BuiltinMetric",
    "FeedbackComment",
    "FeedbackStats",
    "Filters",
    "GroupBy",
    "Kpis",
    "MetricDefinition",
    "MetricFilter",
    "MetricSeries",
    "ModelUsage",
    "Point",
    "SortKey",
    "UnknownMetric",
    "auto_bucket",
    "breakdown",
    "custom_metric_id",
    "feedback_comments",
    "feedback_stats",
    "kpis",
    "metric_series",
    "metric_value",
    "model_usage",
    "parse_definition",
    "timeseries",
]
