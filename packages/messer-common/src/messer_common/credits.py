"""AI credits ledger (data-plane safe: used by the API, the runtime, the worker and the scheduler).

The balance of an organization is the sum of ``credit_ledger.amount``. Entries:

* ``grant``      — credits included in the plan (trial, every paid month).
* ``purchase``   — credit packs (checkout or auto top-up).
* ``usage``      — model usage charged per run (negative).
* ``adjustment`` — manual corrections from the backoffice (positive or negative, always with a note).

Every write that can be retried carries an ``idempotency_key`` (unique), so replays never double count.
The ledger is written on the owner connection (system sessions): the application role can only read it.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .db.base import new_id
from .db.models import CreditLedger, Subscription
from .logging import get_logger

log = get_logger("messer.credits")

LEDGER_KINDS = ("grant", "usage", "purchase", "adjustment")
AUTO_TOPUP_JOB = "auto_topup"
AUTO_TOPUP_COOLDOWN = timedelta(minutes=10)
AUTO_TOPUP_MAX_PER_DAY = 5


def _dec(value: Decimal | float | int | str) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


async def balance(session: AsyncSession, org_id: uuid.UUID) -> Decimal:
    """Current credit balance (sum of every ledger entry)."""
    total = (
        await session.execute(
            select(func.coalesce(func.sum(CreditLedger.amount), 0)).where(CreditLedger.org_id == org_id)
        )
    ).scalar_one()
    return _dec(total)


async def used_between(
    session: AsyncSession, org_id: uuid.UUID, since: datetime, until: datetime | None = None
) -> Decimal:
    """Credits consumed by usage in ``[since, until)`` (a positive number)."""
    q = select(func.coalesce(func.sum(CreditLedger.amount), 0)).where(
        CreditLedger.org_id == org_id, CreditLedger.kind == "usage", CreditLedger.created_at >= since
    )
    if until is not None:
        q = q.where(CreditLedger.created_at < until)
    return -_dec((await session.execute(q)).scalar_one())


async def add_entry(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    kind: str,
    amount: Decimal | float | int | str,
    note: str | None = None,
    idempotency_key: str | None = None,
    created_by: uuid.UUID | None = None,
    cost_usd: Decimal | float | None = None,
    run_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
) -> bool:
    """Insert a ledger entry. Returns False when ``idempotency_key`` was already recorded (no-op)."""
    if kind not in LEDGER_KINDS:
        raise ValueError(f"unknown ledger kind {kind}")
    values: dict[str, Any] = {
        "id": new_id(),
        "org_id": org_id,
        "kind": kind,
        "amount": _dec(amount),
        "note": note,
        "idempotency_key": idempotency_key,
        "created_by": created_by,
        "cost_usd": _dec(cost_usd) if cost_usd is not None else None,
        "run_id": run_id,
        "project_id": project_id,
    }
    stmt = insert(CreditLedger).values(**values)
    if idempotency_key is not None:
        stmt = stmt.on_conflict_do_nothing(index_elements=[CreditLedger.idempotency_key])
    result = await session.execute(stmt.returning(CreditLedger.id))
    return result.first() is not None


async def charge_usage(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    run_id: uuid.UUID | str,
    project_id: uuid.UUID | None,
    cost_usd: Decimal | float,
    credits: Decimal | float,
    note: str | None = None,
) -> None:
    """Deduct the credits of one run. Idempotent on ``usage:{run_id}`` (safe to call on every retry).

    Zero-cost runs (for example the offline demo model) do not create ledger entries.
    """
    cost = _dec(cost_usd)
    amount = _dec(credits)
    if amount < 0:
        raise ValueError("credits must be a positive amount to deduct")
    if amount == 0 and cost == 0:
        return
    rid = run_id if isinstance(run_id, uuid.UUID) else _parse_uuid(run_id)
    await add_entry(
        session,
        org_id=org_id,
        kind="usage",
        amount=-amount,
        note=note,
        idempotency_key=f"usage:{run_id}",
        cost_usd=cost,
        run_id=rid,
        project_id=project_id,
    )


def _parse_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def auto_topup_config(sub: Subscription | None) -> dict[str, Any]:
    cfg = dict(sub.auto_topup or {}) if sub is not None else {}
    return {
        "enabled": bool(cfg.get("enabled")),
        "threshold": int(cfg.get("threshold") or 0),
        "pack_id": cfg.get("pack_id"),
        "last_requested_at": cfg.get("last_requested_at"),
        "last_status": cfg.get("last_status"),
        "last_error": cfg.get("last_error"),
        "history": list(cfg.get("history") or []),
    }


def auto_topup_allowed_now(cfg: dict[str, Any], now: datetime | None = None) -> bool:
    """Cooldown and daily cap, so a failing card or a runaway workload cannot trigger endless charges."""
    now = now or datetime.now(UTC)
    last = cfg.get("last_requested_at")
    if last:
        try:
            if now - datetime.fromisoformat(str(last)) < AUTO_TOPUP_COOLDOWN:
                return False
        except ValueError:
            pass
    recent = 0
    for item in cfg.get("history") or []:
        try:
            if now - datetime.fromisoformat(str(item)) < timedelta(days=1):
                recent += 1
        except ValueError:
            continue
    return recent < AUTO_TOPUP_MAX_PER_DAY


async def needs_auto_topup(session: AsyncSession, org_id: uuid.UUID) -> bool:
    sub = (await session.execute(select(Subscription).where(Subscription.org_id == org_id))).scalar_one_or_none()
    cfg = auto_topup_config(sub)
    if sub is None or not cfg["enabled"] or not cfg["pack_id"] or not sub.stripe_customer_id:
        return False
    if sub.status not in ("active", "past_due", "trialing"):
        return False
    if not auto_topup_allowed_now(cfg):
        return False
    return await balance(session, org_id) < Decimal(cfg["threshold"])


async def maybe_auto_topup(session: AsyncSession, org_id: uuid.UUID) -> bool:
    """Call after charging usage. When auto top-up is enabled and the balance fell below the threshold,
    request a credit pack purchase (executed by the worker job ``auto_topup``). Returns True if requested.

    The job id is bucketed per 10 minutes so concurrent callers enqueue at most one purchase; the job
    re-checks everything under a row lock. The scheduler sweeps the same condition as a safety net.
    """
    if not await needs_auto_topup(session, org_id):
        return False
    from .queue import enqueue

    bucket = int(time.time() // AUTO_TOPUP_COOLDOWN.total_seconds())
    try:
        await enqueue(AUTO_TOPUP_JOB, str(org_id), _job_id=f"auto_topup:{org_id}:{bucket}")
    except Exception as exc:  # Redis down: the scheduler sweep will retry
        log.warning("credits.auto_topup_enqueue_failed", org_id=str(org_id), error=repr(exc))
        return False
    return True
