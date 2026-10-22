"""Backoffice read models (/admin, superadmins only): organizations, usage, margins and business metrics.

Money conventions: subscription prices and invoices are EUR; model cost is USD (``credit_ledger.cost_usd``
of usage entries, i.e. what the model providers charge us); credits revenue is the USD value of the
credits consumed (``credits × MESSER_CREDIT_USD``). Margin = credits revenue − model cost. No currency
conversion is applied anywhere.

MRR counts paid subscriptions (``active`` and ``past_due``) of the current billing mode (test-mode
subscriptions only while billing runs in test mode): monthly price, or annual price / 12.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, exists, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.budgets import period_bounds
from messer_common.db.models import (
    AuditLog,
    Connection,
    CreditLedger,
    Deployment,
    Invoice,
    KbFile,
    Membership,
    Org,
    Plan,
    Project,
    Run,
    Subscription,
    User,
)
from messer_common.settings import get_settings

from .billing import current_test_mode

PAID = ("active", "past_due")
ZERO = Decimal("0")


def credit_usd() -> Decimal:
    return Decimal(str(get_settings().messer_credit_usd))


def mrr_of(sub: Subscription | None, plan: Plan | None) -> Decimal:
    if sub is None or plan is None or sub.status not in PAID:
        return ZERO
    if sub.interval == "year":
        return (Decimal(plan.price_year_eur) / 12).quantize(Decimal("0.01"))
    return Decimal(plan.price_month_eur)


def _dec(value: Any) -> Decimal:
    return Decimal(str(value)) if value is not None else ZERO


def _org_stats_query(month_start: datetime) -> tuple[Any, tuple[Any, Any, Any]]:
    """Organizations with usage aggregates. Also returns the (usage, last_login, owners) subqueries."""
    members = select(Membership.org_id.label("org_id"), func.count().label("n")).group_by(Membership.org_id).subquery()
    projects = (
        select(Project.org_id.label("org_id"), func.count().label("n"))
        .where(Project.archived_at.is_(None))
        .group_by(Project.org_id)
        .subquery()
    )
    runs = (
        select(Run.org_id.label("org_id"), func.count().label("n"))
        .where(Run.started_at >= month_start)
        .group_by(Run.org_id)
        .subquery()
    )
    usage = (
        select(
            CreditLedger.org_id.label("org_id"),
            (-func.sum(CreditLedger.amount)).label("credits"),
            func.coalesce(func.sum(CreditLedger.cost_usd), 0).label("cost"),
        )
        .where(CreditLedger.kind == "usage", CreditLedger.created_at >= month_start)
        .group_by(CreditLedger.org_id)
        .subquery()
    )
    balances = (
        select(CreditLedger.org_id.label("org_id"), func.sum(CreditLedger.amount).label("balance"))
        .group_by(CreditLedger.org_id)
        .subquery()
    )
    last_login = (
        select(Membership.org_id.label("org_id"), func.max(User.last_login_at).label("last"))
        .join(User, User.id == Membership.user_id)
        .group_by(Membership.org_id)
        .subquery()
    )
    owners = (
        select(Membership.org_id.label("org_id"), func.min(User.email).label("email"))
        .join(User, User.id == Membership.user_id)
        .where(Membership.role == "owner")
        .group_by(Membership.org_id)
        .subquery()
    )
    return (
        select(
            Org,
            Subscription,
            Plan,
            func.coalesce(members.c.n, 0),
            func.coalesce(projects.c.n, 0),
            func.coalesce(runs.c.n, 0),
            func.coalesce(usage.c.credits, 0),
            func.coalesce(usage.c.cost, 0),
            func.coalesce(balances.c.balance, 0),
            last_login.c.last,
            owners.c.email,
        )
        .outerjoin(Subscription, Subscription.org_id == Org.id)
        .outerjoin(Plan, Plan.id == func.coalesce(Subscription.plan_id, Org.plan_id))
        .outerjoin(members, members.c.org_id == Org.id)
        .outerjoin(projects, projects.c.org_id == Org.id)
        .outerjoin(runs, runs.c.org_id == Org.id)
        .outerjoin(usage, usage.c.org_id == Org.id)
        .outerjoin(balances, balances.c.org_id == Org.id)
        .outerjoin(last_login, last_login.c.org_id == Org.id)
        .outerjoin(owners, owners.c.org_id == Org.id)
    ), (usage, last_login, owners)


def _row_to_dict(row: Any) -> dict[str, Any]:
    org, sub, plan, members, projects, runs, credits, cost, bal, last_login, owner_email = row
    credits_used = _dec(credits)
    model_cost = _dec(cost)
    revenue = (credits_used * credit_usd()).quantize(Decimal("0.0001"))
    last_active = max([d for d in (org.last_active_at, last_login) if d is not None], default=None)
    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "status": org.status,
        "blocked_reason": org.blocked_reason,
        "created_at": org.created_at,
        "owner_email": owner_email,
        "plan_id": plan.id if plan else None,
        "plan_name": plan.name if plan else None,
        "subscription_status": sub.status if sub else "none",
        "interval": sub.interval if sub else None,
        "trial_ends_at": sub.trial_ends_at if sub else None,
        "test_mode": bool(sub.test_mode) if sub else False,
        "mrr_eur": mrr_of(sub, plan),
        "members": int(members),
        "projects": int(projects),
        "runs_month": int(runs),
        "credits_used_month": credits_used,
        "credits_balance": _dec(bal),
        "model_cost_usd_month": model_cost,
        "credits_revenue_usd_month": revenue,
        "margin_usd_month": (revenue - model_cost).quantize(Decimal("0.0001")),
        "last_active_at": last_active,
    }


async def list_orgs(
    session: AsyncSession,
    *,
    q: str | None = None,
    status: str | None = None,
    payment_status: str | None = None,
    plan_id: str | None = None,
    sort: str = "created",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    month_start, _ = period_bounds("month")
    query, (usage, last_login, owners) = _org_stats_query(month_start)
    filters: list[Any] = []
    if q:
        like = f"%{q.strip()}%"
        filters.append(or_(Org.name.ilike(like), Org.slug.ilike(like), owners.c.email.ilike(like)))
    if status:
        filters.append(Org.status == status)
    if payment_status:
        filters.append(func.coalesce(Subscription.status, "none") == payment_status)
    if plan_id:
        filters.append(func.coalesce(Subscription.plan_id, Org.plan_id) == plan_id)
    if filters:
        query = query.where(and_(*filters))
    total = (await session.execute(select(func.count()).select_from(query.order_by(None).subquery()))).scalar_one()
    order = {
        "name": [Org.name.asc()],
        "cost": [func.coalesce(usage.c.cost, 0).desc(), Org.created_at.desc()],
        "last_active": [last_login.c.last.desc().nulls_last(), Org.created_at.desc()],
    }.get(sort, [Org.created_at.desc()])
    rows = (await session.execute(query.order_by(*order).limit(limit).offset(offset))).all()
    return [_row_to_dict(r) for r in rows], int(total)


async def org_row(session: AsyncSession, org_id: uuid.UUID) -> dict[str, Any] | None:
    month_start, _ = period_bounds("month")
    query, _ = _org_stats_query(month_start)
    row = (await session.execute(query.where(Org.id == org_id))).first()
    return _row_to_dict(row) if row is not None else None


async def org_members(session: AsyncSession, org_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.org_id == org_id)
            .order_by(Membership.created_at)
        )
    ).all()
    return [
        {
            "user_id": u.id,
            "email": u.email,
            "name": u.name,
            "role": m.role,
            "status": u.status,
            "is_superadmin": u.is_superadmin,
            "last_login_at": u.last_login_at,
            "joined_at": m.created_at,
        }
        for m, u in rows
    ]


async def org_projects(session: AsyncSession, org_id: uuid.UUID) -> list[dict[str, Any]]:
    month_start, _ = period_bounds("month")
    runs = (
        select(
            Run.project_id.label("project_id"),
            func.count().label("n"),
            func.coalesce(func.sum(Run.cost_usd), 0).label("cost"),
        )
        .where(Run.org_id == org_id, Run.started_at >= month_start)
        .group_by(Run.project_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(Project, func.coalesce(runs.c.n, 0), func.coalesce(runs.c.cost, 0))
            .outerjoin(runs, runs.c.project_id == Project.id)
            .where(Project.org_id == org_id)
            .order_by(Project.created_at.desc())
        )
    ).all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "created_at": p.created_at,
            "archived_at": p.archived_at,
            "template_id": p.template_id,
            "runs_month": int(n),
            "cost_usd_month": _dec(cost),
        }
        for p, n, cost in rows
    ]


async def recent_audit(
    session: AsyncSession, *, org_id: uuid.UUID | None = None, action_prefix: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    actor = User.__table__.alias("actor")
    imp = User.__table__.alias("imp")
    q = (
        select(AuditLog, actor.c.email, imp.c.email)
        .outerjoin(actor, actor.c.id == AuditLog.actor_id)
        .outerjoin(imp, imp.c.id == AuditLog.impersonated_by)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    if org_id is not None:
        q = q.where(AuditLog.org_id == org_id)
    if action_prefix:
        q = q.where(AuditLog.action.like(f"{action_prefix}%"))
    rows = (await session.execute(q)).all()
    return [
        {
            "id": a.id,
            "created_at": a.created_at,
            "org_id": a.org_id,
            "action": a.action,
            "actor_email": actor_email,
            "impersonated_by_email": imp_email,
            "entity_type": a.entity_type,
            "entity_id": a.entity_id,
            "diff": a.diff,
            "ip": a.ip,
        }
        for a, actor_email, imp_email in rows
    ]


# ============================================================================= business metrics


def _trunc(unit: str, column: Any) -> Any:
    """``date_trunc`` with the unit inlined, so SELECT and GROUP BY render the identical expression."""
    assert unit in ("week", "month")
    return func.date_trunc(literal_column(f"'{unit}'"), column)


def _month_floor(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _months_back(now: datetime, months: int) -> list[datetime]:
    first = _month_floor(now)
    out: list[datetime] = []
    year, month = first.year, first.month
    for _ in range(months):
        out.append(first.replace(year=year, month=month))
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return list(reversed(out))


async def business_metrics(
    session: AsyncSession, *, weeks: int = 12, months: int = 6, now: datetime | None = None
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    test_mode = current_test_mode()

    # ------------------------------------------------------------------ MRR
    paid = (
        await session.execute(
            select(Subscription, Plan)
            .join(Plan, Plan.id == Subscription.plan_id)
            .join(Org, Org.id == Subscription.org_id)
            .where(Subscription.status.in_(PAID), Subscription.test_mode.is_(test_mode))
        )
    ).all()
    by_plan: dict[str, dict[str, Any]] = {}
    mrr = ZERO
    for sub, plan in paid:
        value = mrr_of(sub, plan)
        mrr += value
        entry = by_plan.setdefault(
            plan.id, {"plan_id": plan.id, "plan_name": plan.name, "subscriptions": 0, "mrr_eur": ZERO}
        )
        entry["subscriptions"] += 1
        entry["mrr_eur"] += value
    status_counts = dict(
        (await session.execute(select(Subscription.status, func.count()).group_by(Subscription.status))).all()
    )
    trials_active = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Subscription)
                .where(Subscription.status == "trialing", Subscription.trial_ends_at > now)
            )
        ).scalar_one()
    )

    # ------------------------------------------------------------------ sign-ups per week
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    since_weeks = week_start - timedelta(weeks=weeks - 1)
    user_weeks = dict(
        (
            await session.execute(
                select(_trunc("week", User.created_at), func.count())
                .where(User.created_at >= since_weeks)
                .group_by(_trunc("week", User.created_at))
            )
        ).all()
    )
    org_weeks = dict(
        (
            await session.execute(
                select(_trunc("week", Org.created_at), func.count())
                .where(Org.created_at >= since_weeks)
                .group_by(_trunc("week", Org.created_at))
            )
        ).all()
    )

    def week_count(table: dict[Any, Any], start: datetime) -> int:
        for key, value in table.items():
            if key is not None and key.date() == start.date():
                return int(value)
        return 0

    signups = []
    for i in range(weeks):
        start = since_weeks + timedelta(weeks=i)
        signups.append(
            {
                "week_start": start.date().isoformat(),
                "users": week_count(user_weeks, start),
                "orgs": week_count(org_weeks, start),
            }
        )

    # ------------------------------------------------------------------ trial → paid (90-day cohort)
    cohort_since = now - timedelta(days=90)
    cohort = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(Subscription.stripe_subscription_id.is_not(None) | Subscription.status.in_(PAID)),
                func.count().filter(
                    Subscription.status == "trialing",
                    Subscription.trial_ends_at < now,
                    Subscription.stripe_subscription_id.is_(None),
                ),
            )
            .select_from(Org)
            .join(Subscription, Subscription.org_id == Org.id)
            .where(Org.created_at >= cohort_since)
        )
    ).one()
    started, converted, expired = (int(x) for x in cohort)

    # ------------------------------------------------------------------ churn (30 days)
    churn_since = now - timedelta(days=30)
    churned = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Subscription)
                .where(
                    Subscription.status == "canceled",
                    Subscription.canceled_at >= churn_since,
                    Subscription.test_mode.is_(test_mode),
                )
            )
        ).scalar_one()
    )
    active_paid = len(paid)
    churn_base = active_paid + churned

    # ------------------------------------------------------------------ AI cost vs revenue per month
    month_starts = _months_back(now, months)
    first_month = month_starts[0]
    usage_rows = (
        await session.execute(
            select(
                _trunc("month", CreditLedger.created_at),
                func.coalesce(func.sum(CreditLedger.cost_usd), 0),
                -func.coalesce(func.sum(CreditLedger.amount), 0),
            )
            .where(CreditLedger.kind == "usage", CreditLedger.created_at >= first_month)
            .group_by(_trunc("month", CreditLedger.created_at))
        )
    ).all()
    invoice_filter: list[Any] = [Invoice.status == "paid", Invoice.created_at >= first_month]
    if not test_mode:
        invoice_filter.append(Invoice.stripe_invoice_id.not_like("in_sim_%"))
    invoice_rows = (
        await session.execute(
            select(_trunc("month", Invoice.created_at), func.coalesce(func.sum(Invoice.amount_paid_eur), 0))
            .where(*invoice_filter)
            .group_by(_trunc("month", Invoice.created_at))
        )
    ).all()

    def month_key(value: datetime) -> str:
        return value.strftime("%Y-%m")

    usage_by_month = {month_key(m): (_dec(c), _dec(cr)) for m, c, cr in usage_rows if m is not None}
    invoices_by_month = {month_key(m): _dec(v) for m, v in invoice_rows if m is not None}
    rate = credit_usd()
    series = []
    for m in month_starts:
        key = month_key(m)
        cost, credits = usage_by_month.get(key, (ZERO, ZERO))
        revenue_usd = (credits * rate).quantize(Decimal("0.01"))
        series.append(
            {
                "month": key,
                "ai_cost_usd": cost.quantize(Decimal("0.01")),
                "credits_used": credits,
                "credits_revenue_usd": revenue_usd,
                "margin_usd": (revenue_usd - cost).quantize(Decimal("0.01")),
                "billed_revenue_eur": invoices_by_month.get(key, ZERO),
            }
        )

    # ------------------------------------------------------------------ activation funnel (90-day cohort)
    in_cohort = Org.created_at >= cohort_since

    async def count_where(*conditions: Any) -> int:
        return int(
            (await session.execute(select(func.count()).select_from(Org).where(in_cohort, *conditions))).scalar_one()
        )

    funnel = [
        {"step": "signed_up", "orgs": await count_where()},
        {"step": "project", "orgs": await count_where(exists().where(Project.org_id == Org.id))},
        {
            "step": "data",
            "orgs": await count_where(
                or_(exists().where(KbFile.org_id == Org.id), exists().where(Connection.org_id == Org.id))
            ),
        },
        {"step": "test", "orgs": await count_where(exists().where(Run.org_id == Org.id))},
        {"step": "deploy", "orgs": await count_where(exists().where(Deployment.org_id == Org.id))},
        {
            "step": "paid",
            "orgs": await count_where(
                exists().where(
                    Subscription.org_id == Org.id,
                    or_(Subscription.stripe_subscription_id.is_not(None), Subscription.status.in_(PAID)),
                )
            ),
        },
    ]
    totals = {
        "orgs": int((await session.execute(select(func.count()).select_from(Org))).scalar_one()),
        "users": int((await session.execute(select(func.count()).select_from(User))).scalar_one()),
    }
    current = series[-1] if series else None
    return {
        "test_mode": test_mode,
        "generated_at": now,
        "mrr_eur": mrr,
        "arr_eur": mrr * 12,
        "paid_subscriptions": active_paid,
        "trials_active": trials_active,
        "past_due": int(status_counts.get("past_due", 0)),
        "mrr_by_plan": sorted(by_plan.values(), key=lambda e: e["mrr_eur"], reverse=True),
        "signups": signups,
        "trial_conversion": {
            "window_days": 90,
            "trials_started": started,
            "converted": converted,
            "expired_unconverted": expired,
            "rate": round(converted / started, 4) if started else None,
        },
        "churn": {
            "window_days": 30,
            "canceled": churned,
            "base": churn_base,
            "rate": round(churned / churn_base, 4) if churn_base else None,
        },
        "ai_cost_vs_revenue": series,
        "current_month": current,
        "activation_funnel": funnel,
        "totals": totals,
    }
