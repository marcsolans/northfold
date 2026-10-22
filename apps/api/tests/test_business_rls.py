"""Row level security of the business tables: simulated checkouts and billing notices are readable only
inside their organization (owners / admins) and never writable by the application role."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from messer_common.db import RLS_TABLES, Principal, rls_session, system_session
from messer_common.db.models import Membership
from messer_common.db.models.business import BillingNotice, SimulatedCheckout


async def _seed(org_id: uuid.UUID) -> None:
    async with system_session() as s:
        s.add(
            SimulatedCheckout(
                org_id=org_id,
                kind="credit_pack",
                pack_id="pack_5k",
                amount_eur=Decimal("55"),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        s.add(BillingNotice(org_id=org_id, kind="trial_day_1"))


async def test_business_tables_are_registered_with_rls() -> None:
    assert RLS_TABLES["simulated_checkouts"] == {"read": "owner", "write": "system", "delete": "system"}
    assert RLS_TABLES["billing_notices"] == {"read": "admin", "write": "system", "delete": "system"}
    async with system_session() as s:
        rows = dict(
            (
                await s.execute(
                    text(
                        "select relname, relrowsecurity from pg_class "
                        "where relname in ('simulated_checkouts', 'billing_notices')"
                    )
                )
            ).all()
        )
    assert rows == {"simulated_checkouts": True, "billing_notices": True}


async def test_business_tables_isolation(make_org, make_user) -> None:  # type: ignore[no-untyped-def]
    org_a, owner_a = await make_org(name="A")
    org_b, owner_b = await make_org(name="B")
    viewer_b = await make_user()
    async with system_session() as s:
        s.add(Membership(org_id=org_b.id, user_id=viewer_b.id, role="viewer"))
    await _seed(org_a.id)
    await _seed(org_b.id)

    async with rls_session(Principal(user_id=owner_a.id, org_id=org_a.id)) as s:
        for model in (SimulatedCheckout, BillingNotice):
            other = (
                await s.execute(select(func.count()).select_from(model).where(model.org_id == org_b.id))
            ).scalar_one()
            own = (
                await s.execute(select(func.count()).select_from(model).where(model.org_id == org_a.id))
            ).scalar_one()
            assert (other, own) == (0, 1), model.__tablename__
    async with rls_session(Principal(user_id=viewer_b.id, org_id=org_b.id)) as s:
        for model in (SimulatedCheckout, BillingNotice):
            assert (await s.execute(select(func.count()).select_from(model))).scalar_one() == 0
    with pytest.raises((ProgrammingError, DBAPIError)):
        async with rls_session(Principal(user_id=owner_a.id, org_id=org_a.id)) as s:
            s.add(BillingNotice(org_id=org_a.id, kind="forged"))
            await s.flush()
    # No update/delete policy for the application role: rows are untouchable even by the owner.
    async with rls_session(Principal(user_id=owner_b.id, org_id=org_b.id)) as s:
        updated = await s.execute(text("update simulated_checkouts set status = 'completed'"))
        deleted = await s.execute(text("delete from billing_notices"))
        assert updated.rowcount == 0 and deleted.rowcount == 0  # type: ignore[attr-defined]
