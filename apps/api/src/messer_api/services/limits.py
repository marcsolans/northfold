"""Plan limits and feature gates (contracts §2).

* ``require_feature(session, org_id, feature)`` raises ``PlanLimitExceeded`` (402, ``plan_limit``) with
  details ``{"feature", "upgrade_to"}`` when the organization's plan does not include ``feature``.
* ``require_capacity(session, org_id, limit_key, used)`` raises when ``used`` already reaches the plan
  limit (``-1`` means unlimited). Details: ``{"limit", "value", "used", "upgrade_to"}``.

``upgrade_to`` is the cheapest public plan that unlocks the feature or a higher limit (``None`` if none).
Helpers for the places that enforce limits today: seats (invitations) and projects (creation).
Works with RLS sessions (any member can read plans, subscriptions and projects) and system sessions.
Organizations without any plan (created by the system without a trial) are not limited.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db.models import FeatureFlag, Invitation, Membership, Org, Plan, Project, Subscription
from messer_common.plans import FEATURES, UNLIMITED, limit_value, plan_has_feature

from ..errors import PlanLimitExceeded

LIMIT_KEYS = ("seats", "projects", "runs_month", "credits_month", "storage_gb")

_CAPACITY_MESSAGES = {
    "seats": "Tu plan {plan} incluye {value} usuarios. Mejora el plan para invitar a más.",
    "projects": "Tu plan {plan} incluye {value} proyectos. Mejora el plan para crear más.",
    "runs_month": "Tu plan {plan} incluye {value} ejecuciones al mes. Mejora el plan para seguir ejecutando.",
    "credits_month": "Tu plan {plan} incluye {value} créditos al mes.",
    "storage_gb": "Tu plan {plan} incluye {value} GB de almacenamiento. Mejora el plan para subir más archivos.",
}


async def org_plan(session: AsyncSession, org_id: uuid.UUID) -> Plan | None:
    """The plan in force: the subscription's plan, or the organization's plan when there is none."""
    plan_id = (
        await session.execute(select(Subscription.plan_id).where(Subscription.org_id == org_id))
    ).scalar_one_or_none()
    if plan_id is None:
        plan_id = (await session.execute(select(Org.plan_id).where(Org.id == org_id))).scalar_one_or_none()
    return await session.get(Plan, plan_id) if plan_id else None


async def _public_plans(session: AsyncSession) -> list[Plan]:
    rows = await session.execute(
        select(Plan).where(Plan.public.is_(True)).order_by(Plan.price_month_eur, Plan.sort_order)
    )
    return list(rows.scalars().all())


async def cheapest_plan_with_feature(session: AsyncSession, feature: str) -> Plan | None:
    return next((p for p in await _public_plans(session) if plan_has_feature(p.limits, feature)), None)


async def cheapest_plan_above(session: AsyncSession, limit_key: str, used: int) -> Plan | None:
    for plan in await _public_plans(session):
        value = limit_value(plan.limits, limit_key)
        if value == UNLIMITED or value > used:
            return plan
    return None


async def require_feature(session: AsyncSession, org_id: uuid.UUID, feature: str) -> None:
    plan = await org_plan(session, org_id)
    if plan is None or plan_has_feature(plan.limits, feature):
        return
    upgrade = await cheapest_plan_with_feature(session, feature)
    label = FEATURES.get(feature, feature)
    if upgrade is not None:
        message = f"Tu plan {plan.name} no incluye {label}. Disponible desde el plan {upgrade.name}."
    else:
        message = f"Tu plan {plan.name} no incluye {label}."
    raise PlanLimitExceeded(
        message,
        details={
            "feature": feature,
            "upgrade_to": upgrade.id if upgrade else None,
            "current_plan": plan.id,
        },
    )


async def require_capacity(session: AsyncSession, org_id: uuid.UUID, limit_key: str, used: int) -> None:
    if limit_key not in LIMIT_KEYS:
        raise ValueError(f"unknown plan limit {limit_key}")
    plan = await org_plan(session, org_id)
    if plan is None:
        return
    value = limit_value(plan.limits, limit_key)
    if value == UNLIMITED or used < value:
        return
    upgrade = await cheapest_plan_above(session, limit_key, used)
    raise PlanLimitExceeded(
        _CAPACITY_MESSAGES[limit_key].format(plan=plan.name, value=value),
        details={
            "limit": limit_key,
            "value": value,
            "used": used,
            "upgrade_to": upgrade.id if upgrade else None,
            "current_plan": plan.id,
        },
    )


async def seats_used(session: AsyncSession, org_id: uuid.UUID) -> int:
    """Members plus pending (unexpired, unrevoked) invitations."""
    now = datetime.now(UTC)
    members = (
        await session.execute(select(func.count()).select_from(Membership).where(Membership.org_id == org_id))
    ).scalar_one()
    pending = (
        await session.execute(
            select(func.count())
            .select_from(Invitation)
            .where(
                Invitation.org_id == org_id,
                Invitation.accepted_at.is_(None),
                Invitation.revoked_at.is_(None),
                Invitation.expires_at > now,
            )
        )
    ).scalar_one()
    return int(members) + int(pending)


async def require_seat(session: AsyncSession, org_id: uuid.UUID) -> None:
    """Before inviting someone: one more seat must fit in the plan."""
    await require_capacity(session, org_id, "seats", await seats_used(session, org_id))


async def projects_used(session: AsyncSession, org_id: uuid.UUID) -> int:
    return int(
        (
            await session.execute(
                select(func.count()).select_from(Project).where(Project.org_id == org_id, Project.archived_at.is_(None))
            )
        ).scalar_one()
    )


async def require_project_capacity(session: AsyncSession, org_id: uuid.UUID) -> None:
    """Before creating (or duplicating / cloning a template into) a project."""
    await require_capacity(session, org_id, "projects", await projects_used(session, org_id))


async def feature_flag_enabled(session: AsyncSession, key: str, org_id: uuid.UUID | None = None) -> bool:
    """Global feature flag with optional targeting ``{"plans": [...], "orgs": [...]}`` (managed in /admin).

    ``enabled`` is the master switch: a disabled flag is off for everyone. An enabled flag without
    targeting is on for everyone; with targeting, only for the listed organizations and plans.
    """
    flag = await session.get(FeatureFlag, key)
    if flag is None or not flag.enabled:
        return False
    targeting: dict[str, Any] = flag.targeting or {}
    orgs = [str(o) for o in targeting.get("orgs") or []]
    plans = [str(p) for p in targeting.get("plans") or []]
    if not orgs and not plans:
        return True
    if org_id is None:
        return False
    if str(org_id) in orgs:
        return True
    if plans:
        plan = await org_plan(session, org_id)
        return plan is not None and plan.id in plans
    return False
