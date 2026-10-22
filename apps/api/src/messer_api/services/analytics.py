"""Governance services: request filters, CSV export, alarm evaluation and model policy.

Alarm evaluation (``run_alarm_sweep``) is called every minute by the scheduler (``messer_scheduler.tasks.alarms``)
and on demand by the API. Each alarm is evaluated in its own transaction with ``FOR UPDATE SKIP LOCKED`` so two
evaluators never transition the same alarm twice. Transitions ok → firing → ok are stored in ``alarm_events``;
admins get an in-app notification for every transition, the ``alarm_fired`` email when it fires (if the alarm
has the email channel) and a Slack message (if it has the Slack channel, a target channel and the organization
has an active Slack connection — otherwise the reason it was skipped is logged and kept in the event).
"""

from __future__ import annotations

import asyncio
import csv
import fnmatch
import io
import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.analytics import BUILTIN_METRICS, AnalyticsError, Filters, UnknownMetric, metric_value
from messer_common.analytics.metrics import custom_metric_id
from messer_common.billing_notify import Recipient, notify_org, org_recipients
from messer_common.db import system_session
from messer_common.db.base import new_id
from messer_common.db.models import Alarm, Connection, CustomMetric, ModelPrice, Notification, Project
from messer_common.db.models.governance import AlarmEvent
from messer_common.logging import get_logger
from messer_common.models_config import DEMO_MODEL, load_models_config
from messer_common.settings import get_settings

from ..errors import ApiError

log = get_logger("messer.governance")

COMPARATORS: tuple[str, ...] = (">", ">=", "<", "<=", "==", "!=")
ALARM_CHANNELS: tuple[str, ...] = ("email", "slack")
SLACK_TIMEOUT_S = 15.0
MIN_REEVALUATION_S = 45


class InvalidQuery(ApiError):
    status_code = 422
    code = "invalid_analytics_query"


def build_filters(
    org_id: uuid.UUID,
    *,
    since: datetime | None,
    until: datetime | None,
    project_id: uuid.UUID | None = None,
    environment: str | None = None,
    channel: str | None = None,
    workforce: str | None = None,
) -> Filters:
    try:
        return Filters.build(
            org_id,
            since=since,
            until=until,
            project_id=project_id,
            environment=environment,
            channel=channel,
            workforce_name=workforce,
        )
    except AnalyticsError as exc:
        raise InvalidQuery(exc.message, code=exc.code) from exc


# ------------------------------------------------------------------------------------------------ CSV

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value)
    # Spreadsheet formula injection: a text cell starting with a formula character is prefixed with a quote.
    if text.startswith(_FORMULA_PREFIXES) and not _is_number(text):
        return "'" + text
    return text


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def to_csv(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow([_cell(v) for v in row])
    return buf.getvalue()


# ------------------------------------------------------------------------------------------------ alarms


def compare(value: float, comparator: str, threshold: float) -> bool:
    if comparator == ">":
        return value > threshold
    if comparator == ">=":
        return value >= threshold
    if comparator == "<":
        return value < threshold
    if comparator == "<=":
        return value <= threshold
    if comparator == "==":
        return value == threshold
    if comparator == "!=":
        return value != threshold
    raise ValueError(f"unknown comparator {comparator!r}")


def alarm_filters(alarm: Alarm, now: datetime) -> Filters:
    cfg = alarm.config or {}
    return Filters(
        org_id=alarm.org_id,
        since=now - timedelta(minutes=alarm.window_minutes),
        until=now,
        project_id=alarm.project_id,
        environment=cfg.get("environment") or None,
        channel=cfg.get("channel") or None,
        workforce_name=cfg.get("workforce_name") or None,
    )


@dataclass(slots=True)
class MetricLabel:
    es: str
    en: str
    unit: str

    def get(self, locale: str) -> str:
        return self.en if locale == "en" else self.es


async def metric_label(session: AsyncSession, org_id: uuid.UUID, metric: str) -> MetricLabel:
    builtin = BUILTIN_METRICS.get(metric)
    if builtin is not None:
        return MetricLabel(builtin.label_es, builtin.label_en, builtin.unit)
    try:
        metric_id = custom_metric_id(metric)
    except UnknownMetric:
        return MetricLabel(metric, metric, "count")
    if metric_id is not None:
        row = await session.get(CustomMetric, metric_id)
        if row is not None and row.org_id == org_id:
            from messer_common.analytics.metrics import metric_unit

            return MetricLabel(row.name, row.name, metric_unit(metric, row))
    return MetricLabel(metric, metric, "count")


def format_value(value: float | None, unit: str, locale: str = "es") -> str:
    if value is None:
        return "sin datos" if locale != "en" else "no data"
    if unit == "percent":
        return f"{value:.1f} %"
    if unit == "ms":
        return f"{value:.0f} ms"
    if unit == "usd":
        return f"{value:.4f} USD" if abs(value) < 1 else f"{value:.2f} USD"
    if unit == "credits":
        return f"{value:.2f}"
    if float(value).is_integer():
        return f"{int(value)}"
    return f"{value:.2f}"


def alarm_url(alarm: Alarm) -> str:
    return f"{get_settings().messer_web_url}/app/analytics/alarms?alarm={alarm.id}"


@dataclass(slots=True)
class AlarmOutcome:
    alarm_id: uuid.UUID
    value: float | None
    breached: bool
    state: str
    transitioned: bool = False
    error: str | None = None
    delivery: dict[str, Any] = field(default_factory=dict)


async def compute(session: AsyncSession, alarm: Alarm, now: datetime) -> tuple[float | None, bool, str | None]:
    """Current value of the alarm's metric and whether it breaches the threshold (no side effects)."""
    try:
        value = await metric_value(session, alarm.metric, alarm_filters(alarm, now))
    except UnknownMetric:
        return None, False, "unknown_metric"
    except ValueError as exc:  # invalid custom metric definition stored before a schema change
        log.warning("alarm.metric_invalid", alarm_id=str(alarm.id), error=str(exc))
        return None, False, "invalid_metric"
    breached = value is not None and compare(value, alarm.comparator, float(alarm.threshold))
    return value, breached, None


def _by_locale(people: list[Recipient]) -> dict[str, list[Recipient]]:
    groups: dict[str, list[Recipient]] = {}
    for p in people:
        groups.setdefault("en" if p.locale == "en" else "es", []).append(p)
    return groups


async def _scope_name(session: AsyncSession, alarm: Alarm) -> str | None:
    if alarm.project_id is None:
        return None
    project = await session.get(Project, alarm.project_id)
    return project.name if project is not None else None


def _resolved_text(name: str, metric: str, value: str, locale: str) -> tuple[str, str]:
    if locale == "en":
        return f"Alarm resolved: {name}", f"Metric {metric} is back within the threshold ({value})."
    return f"Alarma resuelta: {name}", f"La métrica {metric} ha vuelto al umbral ({value})."


def _slack_text(alarm: Alarm, label: MetricLabel, value: float | None, firing: bool, scope: str | None) -> str:
    where = f" · {scope}" if scope else ""
    shown = format_value(value, label.unit)
    threshold = format_value(float(alarm.threshold), label.unit)
    if firing:
        head = f"Alarma activada: {alarm.name}{where}"
        body = f"{label.es} = {shown} (umbral {alarm.comparator} {threshold}, últimos {alarm.window_minutes} min)"
    else:
        head = f"Alarma resuelta: {alarm.name}{where}"
        body = f"{label.es} = {shown} (umbral {alarm.comparator} {threshold})"
    return f"{head}\n{body}\n{alarm_url(alarm)}"


async def post_slack(session: AsyncSession, alarm: Alarm, text: str) -> str:
    """Post to the alarm's Slack channel through the org's Slack connection. Returns the delivery status."""
    target = str((alarm.config or {}).get("slack_channel") or "").strip()
    if not target:
        log.info("alarm.slack_skipped", alarm_id=str(alarm.id), reason="no_channel")
        return "skipped:no_channel"
    conn = (
        await session.execute(
            select(Connection)
            .where(
                Connection.org_id == alarm.org_id,
                Connection.connector_key == "slack",
                Connection.status.in_(("active", "demo")),
            )
            .order_by(Connection.demo.asc(), Connection.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if conn is None:
        log.info("alarm.slack_skipped", alarm_id=str(alarm.id), reason="no_slack_connection")
        return "skipped:no_connection"
    try:
        from messer_connectors.base import ConnectorError
        from messer_connectors.credentials import load_context
        from messer_connectors.registry import get_adapter
    except ImportError:
        log.warning("alarm.slack_skipped", alarm_id=str(alarm.id), reason="connectors_unavailable")
        return "skipped:connectors_unavailable"
    try:
        ctx = await load_context(session, conn.id)
        adapter = get_adapter("slack")
        await asyncio.wait_for(
            adapter.run_action(ctx, "post_message", {"channel": target, "text": text}), timeout=SLACK_TIMEOUT_S
        )
    except ConnectorError as exc:
        log.warning("alarm.slack_failed", alarm_id=str(alarm.id), code=exc.code, error=exc.message)
        return f"failed:{exc.code}"
    except TimeoutError:
        log.warning("alarm.slack_failed", alarm_id=str(alarm.id), code="timeout")
        return "failed:timeout"
    return "demo" if conn.demo else "posted"


async def _deliver(session: AsyncSession, alarm: Alarm, value: float | None, firing: bool) -> dict[str, Any]:
    label = await metric_label(session, alarm.org_id, alarm.metric)
    scope = await _scope_name(session, alarm)
    people = await org_recipients(session, alarm.org_id, "admin")
    url = alarm_url(alarm)
    channels = {str(c) for c in (alarm.channels or [])}
    delivery: dict[str, Any] = {"in_app": len(people), "email": 0}
    if firing:
        for locale, group in _by_locale(people).items():
            context = {
                "alarm": f"{alarm.name} · {scope}" if scope else alarm.name,
                "metric": label.get(locale),
                "value": format_value(value, label.unit, locale),
                "comparator": alarm.comparator,
                "threshold": format_value(float(alarm.threshold), label.unit, locale),
            }
            await notify_org(
                session,
                org_id=alarm.org_id,
                kind="alarm.firing",
                template="alarm_fired",
                context=context,
                url=url,
                email="email" in channels,
                recipients=group,
            )
        if "email" in channels:
            delivery["email"] = len(people)
    else:
        for person in people:
            title, body = _resolved_text(
                alarm.name, label.get(person.locale), format_value(value, label.unit), person.locale
            )
            session.add(
                Notification(
                    id=new_id(),
                    org_id=alarm.org_id,
                    user_id=person.user_id,
                    kind="alarm.resolved",
                    payload={"title": title, "body": body, "url": f"/app/analytics/alarms?alarm={alarm.id}"},
                    channel="in_app",
                )
            )
    if "slack" in channels:
        delivery["slack"] = await post_slack(session, alarm, _slack_text(alarm, label, value, firing, scope))
    return delivery


async def evaluate_alarm(
    alarm_id: uuid.UUID, *, now: datetime | None = None, force: bool = False
) -> AlarmOutcome | None:
    """Evaluate one alarm and apply its state transition. ``None`` when it is locked, disabled or not due."""
    now = now or datetime.now(UTC)
    async with system_session() as s:
        alarm = (
            await s.execute(select(Alarm).where(Alarm.id == alarm_id).with_for_update(skip_locked=True))
        ).scalar_one_or_none()
        if alarm is None or not alarm.enabled:
            return None
        if (
            not force
            and alarm.last_evaluated_at is not None
            and timedelta(0) <= now - alarm.last_evaluated_at < timedelta(seconds=MIN_REEVALUATION_S)
        ):
            return None
        value, breached, error = await compute(s, alarm, now)
        alarm.last_evaluated_at = now
        alarm.last_value = value
        outcome = AlarmOutcome(alarm_id=alarm.id, value=value, breached=breached, state=alarm.state, error=error)
        if error is not None:
            log.warning("alarm.evaluation_error", alarm_id=str(alarm.id), metric=alarm.metric, error=error)
            return outcome
        new_state = "firing" if breached else "ok"
        if new_state == alarm.state:
            return outcome
        previous = alarm.state
        alarm.state = new_state
        if new_state == "firing":
            alarm.last_fired_at = now
        delivery = await _deliver(s, alarm, value, firing=new_state == "firing")
        s.add(
            AlarmEvent(
                org_id=alarm.org_id,
                alarm_id=alarm.id,
                from_state=previous,
                to_state=new_state,
                value=value,
                metric=alarm.metric,
                comparator=alarm.comparator,
                threshold=float(alarm.threshold),
                window_minutes=alarm.window_minutes,
                delivery=delivery,
                created_at=now,
            )
        )
        log.info(
            "alarm.transition",
            alarm_id=str(alarm.id),
            org_id=str(alarm.org_id),
            from_state=previous,
            to_state=new_state,
            value=value,
        )
        outcome.state = new_state
        outcome.transitioned = True
        outcome.delivery = delivery
        return outcome


async def run_alarm_sweep(*, now: datetime | None = None, org_id: uuid.UUID | None = None) -> list[AlarmOutcome]:
    """Evaluate every enabled alarm (scheduler, every minute). One failing alarm never stops the sweep."""
    now = now or datetime.now(UTC)
    async with system_session() as s:
        q = select(Alarm.id).where(Alarm.enabled.is_(True))
        if org_id is not None:
            q = q.where(Alarm.org_id == org_id)
        ids = list((await s.execute(q.order_by(Alarm.created_at))).scalars().all())
    outcomes: list[AlarmOutcome] = []
    for alarm_id in ids:
        try:
            outcome = await evaluate_alarm(alarm_id, now=now)
        except Exception as exc:
            log.error("alarm.evaluation_failed", alarm_id=str(alarm_id), error=repr(exc))
            continue
        if outcome is not None:
            outcomes.append(outcome)
    return outcomes


# ------------------------------------------------------------------------------------------------ model policy

GLOB_RE = re.compile(r"^(\*|[a-z0-9*?\[\]_.\-]+/[A-Za-z0-9*?\[\]_.:\-]+)$")
MAX_PATTERNS = 50


@dataclass(slots=True)
class KnownModel:
    model: str
    display_name: str
    provider: str
    tiers: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)


async def known_models(session: AsyncSession) -> list[KnownModel]:
    """Models Messer knows: ``config/models.yaml`` (tiers, Guard, Bedrock, prices) and active ``model_prices``."""
    cfg = load_models_config()
    models: dict[str, KnownModel] = {}

    def add(model: str, display: str | None = None) -> KnownModel:
        entry = models.get(model)
        if entry is None:
            entry = KnownModel(model=model, display_name=display or model, provider=model.split("/", 1)[0])
            models[model] = entry
        elif display and entry.display_name == model:
            entry.display_name = display
        return entry

    for row in cfg.get("prices", []) or []:
        if str(row["model"]) != DEMO_MODEL:
            add(str(row["model"]), str(row.get("display_name") or row["model"]))
    for tier, model in (cfg.get("tiers") or {}).items():
        if str(model) != DEMO_MODEL:
            add(str(model)).tiers.append(str(tier))
    for role, model in (cfg.get("guard") or {}).items():
        if str(model) != DEMO_MODEL:
            add(str(model)).roles.append(f"guard_{role}")
    for model in ((cfg.get("bedrock") or {}).get("models") or {}).keys():
        if str(model) != DEMO_MODEL:
            add(str(model))
    rows = (await session.execute(select(ModelPrice).where(ModelPrice.active.is_(True)))).scalars().all()
    for price in rows:
        if price.model != DEMO_MODEL:
            add(price.model, price.display_name or None)
    order = {"fast": 0, "standard": 1, "powerful": 2}
    return sorted(models.values(), key=lambda m: (min((order.get(t, 9) for t in m.tiers), default=9), m.model))


def policy_decision(rules: dict[str, Any], model: str) -> tuple[bool, str, str | None]:
    """Same semantics as the runtime gateway (``_policy_allows``): deny wins, then the allow list (if any)."""
    deny = [str(p) for p in rules.get("deny", []) or []]
    allow = [str(p) for p in rules.get("allow", []) or []]
    for pattern in deny:
        if fnmatch.fnmatch(model, pattern):
            return False, "denied", pattern
    if not allow:
        return True, "default", None
    for pattern in allow:
        if fnmatch.fnmatch(model, pattern):
            return True, "allowed", pattern
    return False, "not_allowed", None


def normalize_patterns(values: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for raw in values:
        value = raw.strip()
        if value and value not in seen:
            seen.append(value)
    return seen


def validate_policy(rules: dict[str, list[str]], known: list[KnownModel]) -> list[dict[str, Any]]:
    """Errors (list of {field, pattern, code, message}); empty when the policy is valid."""
    errors: list[dict[str, Any]] = []
    names = [m.model for m in known]
    for key in ("allow", "deny"):
        patterns = rules.get(key, [])
        if len(patterns) > MAX_PATTERNS:
            errors.append(
                {"field": key, "pattern": None, "code": "too_many", "message": f"Máximo {MAX_PATTERNS} patrones"}
            )
        for pattern in patterns:
            if not GLOB_RE.match(pattern):
                errors.append(
                    {
                        "field": key,
                        "pattern": pattern,
                        "code": "invalid_glob",
                        "message": "Usa el formato proveedor/modelo con comodines * o ? (p. ej. anthropic/claude-*)",
                    }
                )
            elif not any(fnmatch.fnmatch(n, pattern) for n in names):
                errors.append(
                    {
                        "field": key,
                        "pattern": pattern,
                        "code": "matches_nothing",
                        "message": "El patrón no coincide con ningún modelo conocido",
                    }
                )
    if not errors and known and not any(policy_decision(dict(rules), m.model)[0] for m in known):
        errors.append(
            {
                "field": "allow",
                "pattern": None,
                "code": "blocks_everything",
                "message": "La política bloquearía todos los modelos: ningún agente podría ejecutarse",
            }
        )
    return errors


def preview_policy(rules: dict[str, Any], known: list[KnownModel]) -> dict[str, Any]:
    models: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for m in known:
        allowed, reason, pattern = policy_decision(rules, m.model)
        models.append(
            {
                "model": m.model,
                "display_name": m.display_name,
                "provider": m.provider,
                "tiers": m.tiers,
                "roles": m.roles,
                "allowed": allowed,
                "reason": reason,
                "pattern": pattern,
            }
        )
        if not allowed:
            for tier in m.tiers:
                warnings.append({"code": "tier_blocked", "tier": tier, "model": m.model})
            for role in m.roles:
                warnings.append({"code": "role_blocked", "role": role, "model": m.model})
    return {
        "models": models,
        "allowed_count": sum(1 for m in models if m["allowed"]),
        "total": len(models),
        "warnings": warnings,
    }
