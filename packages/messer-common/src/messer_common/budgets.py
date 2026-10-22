"""Budgets and the pre-run gate used by the runtime (data-plane safe).

``check_budget(session, org_id, project_id)`` answers "may this organization start a run now?":

1. the organization is not blocked and not in read-only billing state;
2. it has AI credits left (unless the plan has unlimited credits);
3. it is under the plan's monthly run limit;
4. no applicable budget (org-wide or the project's) with ``hard_stop`` is exhausted this period.

Spend is the raw model cost (``runs.cost_usd``) of the budget's period (calendar day/week/month, UTC).
Crossing the alert threshold notifies admins once per period (in-app + email); reaching the limit sends
one more notice per period.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from .billing_notify import claim_notice, notify_org
from .billing_state import derive_state
from .credits import balance
from .db.models import Budget, Org, Plan, Project, Run, Subscription
from .plans import UNLIMITED, limit_value
from .settings import get_settings

PERIODS = ("day", "week", "month")

REASON_MESSAGES = {
    "org_blocked": "La organización está bloqueada. Contacta con soporte.",
    "read_only": "La organización está en modo solo lectura. Elige un plan para continuar.",
    "credits_exhausted": "No quedan créditos de IA. Compra un paquete o activa la recarga automática.",
    "runs_limit": "Has alcanzado el límite de ejecuciones mensuales de tu plan.",
    "budget_exceeded": "Se ha alcanzado el presupuesto de este periodo.",
}


@dataclass(slots=True)
class BudgetStatus:
    allowed: bool
    reason: str | None = None
    remaining_usd: Decimal | None = None
    message: str | None = None
    budget_id: uuid.UUID | None = None
    spent_usd: Decimal | None = None
    limit_usd: Decimal | None = None


@dataclass(slots=True)
class BudgetUsage:
    budget: Budget
    period_start: datetime
    period_end: datetime
    spent_usd: Decimal

    @property
    def pct(self) -> int:
        if self.budget.limit_usd <= 0:
            return 100
        return int((self.spent_usd / self.budget.limit_usd * 100).to_integral_value(rounding=ROUND_HALF_UP))

    @property
    def remaining_usd(self) -> Decimal:
        return max(Decimal("0"), Decimal(self.budget.limit_usd) - self.spent_usd)

    @property
    def exceeded(self) -> bool:
        return self.spent_usd >= Decimal(self.budget.limit_usd)

    @property
    def state(self) -> str:
        if self.exceeded:
            return "exceeded"
        if self.pct >= self.budget.alert_threshold_pct:
            return "alert"
        return "ok"


def period_bounds(period: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "day":
        return day, day + timedelta(days=1)
    if period == "week":
        start = day - timedelta(days=day.weekday())
        return start, start + timedelta(days=7)
    start = day.replace(day=1)
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return start, end


async def spend_usd(
    session: AsyncSession, org_id: uuid.UUID, project_id: uuid.UUID | None, since: datetime, until: datetime
) -> Decimal:
    q = select(func.coalesce(func.sum(Run.cost_usd), 0)).where(
        Run.org_id == org_id, Run.started_at >= since, Run.started_at < until
    )
    if project_id is not None:
        q = q.where(Run.project_id == project_id)
    return Decimal(str((await session.execute(q)).scalar_one()))


async def budget_usage(session: AsyncSession, budget: Budget, now: datetime | None = None) -> BudgetUsage:
    start, end = period_bounds(budget.period, now)
    spent = await spend_usd(session, budget.org_id, budget.project_id, start, end)
    return BudgetUsage(budget=budget, period_start=start, period_end=end, spent_usd=spent)


async def runs_this_month(session: AsyncSession, org_id: uuid.UUID, now: datetime | None = None) -> int:
    start, end = period_bounds("month", now)
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(Run)
                .where(Run.org_id == org_id, Run.started_at >= start, Run.started_at < end)
            )
        ).scalar_one()
    )


def _denied(reason: str, **extra: object) -> BudgetStatus:
    status = BudgetStatus(allowed=False, reason=reason, message=REASON_MESSAGES[reason])
    for key, value in extra.items():
        setattr(status, key, value)
    return status


async def check_budget(session: AsyncSession, org_id: uuid.UUID, project_id: uuid.UUID | None) -> BudgetStatus:
    """Pre-run gate for the runtime. Also fires due budget alerts (once per period)."""
    org = await session.get(Org, org_id)
    sub = (await session.execute(select(Subscription).where(Subscription.org_id == org_id))).scalar_one_or_none()
    state = derive_state(org, sub)
    if state.blocked:
        return _denied("org_blocked")
    if state.read_only:
        return _denied("read_only")

    plan_id = state.plan_id
    plan = await session.get(Plan, plan_id) if plan_id else None
    limits = plan.limits if plan is not None else {}
    if limit_value(limits, "credits_month") != UNLIMITED and await balance(session, org_id) <= 0:
        return _denied("credits_exhausted")
    runs_limit = limit_value(limits, "runs_month")
    if plan is not None and runs_limit != UNLIMITED and await runs_this_month(session, org_id) >= runs_limit:
        return _denied("runs_limit")

    scopes: list[ColumnElement[bool]] = [Budget.project_id.is_(None)]
    if project_id is not None:
        scopes.append(Budget.project_id == project_id)
    budgets = (await session.execute(select(Budget).where(Budget.org_id == org_id, or_(*scopes)))).scalars().all()
    tightest: BudgetUsage | None = None
    for budget in budgets:
        usage = await budget_usage(session, budget)
        await _maybe_alert(session, usage)
        if usage.exceeded and budget.hard_stop:
            return _denied(
                "budget_exceeded",
                remaining_usd=Decimal("0"),
                budget_id=budget.id,
                spent_usd=usage.spent_usd,
                limit_usd=Decimal(budget.limit_usd),
            )
        if tightest is None or usage.remaining_usd < tightest.remaining_usd:
            tightest = usage
    if tightest is None:
        return BudgetStatus(allowed=True)
    return BudgetStatus(
        allowed=True,
        remaining_usd=tightest.remaining_usd,
        budget_id=tightest.budget.id,
        spent_usd=tightest.spent_usd,
        limit_usd=Decimal(tightest.budget.limit_usd),
    )


async def _scope_name(session: AsyncSession, budget: Budget) -> str:
    if budget.project_id is not None:
        project = await session.get(Project, budget.project_id)
        if project is not None:
            return project.name
    org = await session.get(Org, budget.org_id)
    return org.name if org is not None else ""


def _usd(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)} USD"


async def _maybe_alert(session: AsyncSession, usage: BudgetUsage) -> int:
    """Threshold alert once per period (atomic on ``last_alerted_at``) and one 'limit reached' notice."""
    budget = usage.budget
    fired = 0
    if usage.pct < budget.alert_threshold_pct:
        return 0
    url = f"{get_settings().messer_web_url}/app/settings/budgets"
    won = (
        await session.execute(
            update(Budget)
            .where(
                Budget.id == budget.id,
                or_(Budget.last_alerted_at.is_(None), Budget.last_alerted_at < usage.period_start),
            )
            .values(last_alerted_at=datetime.now(UTC))
            .returning(Budget.id)
        )
    ).first()
    scope = await _scope_name(session, budget)
    context = {
        "pct": usage.pct,
        "scope": scope,
        "spent": _usd(usage.spent_usd),
        "limit": _usd(Decimal(budget.limit_usd)),
    }
    if won is not None:
        await notify_org(
            session, org_id=budget.org_id, kind="budget.alert", template="budget_alert", context=context, url=url
        )
        fired += 1
    if usage.exceeded and await claim_notice(
        session,
        org_id=budget.org_id,
        kind="budget_exceeded",
        ref=f"{budget.id}:{usage.period_start.date().isoformat()}",
        payload={"spent_usd": str(usage.spent_usd), "limit_usd": str(budget.limit_usd)},
    ):
        await notify_org(
            session,
            org_id=budget.org_id,
            kind="budget.exceeded",
            template="budget_exceeded",
            context={**context, "hard_stop": budget.hard_stop},
            url=url,
        )
        fired += 1
    return fired


async def evaluate_alerts(session: AsyncSession, *, org_id: uuid.UUID | None = None) -> int:
    """Sweep budgets and fire due alerts (scheduler). Returns the number of notices fired."""
    q = select(Budget)
    if org_id is not None:
        q = q.where(Budget.org_id == org_id)
    fired = 0
    for budget in (await session.execute(q.order_by(Budget.created_at))).scalars().all():
        fired += await _maybe_alert(session, await budget_usage(session, budget))
    return fired
