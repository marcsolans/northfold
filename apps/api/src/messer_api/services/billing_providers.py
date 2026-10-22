"""Billing provider adapters.

* :class:`StripeBilling` — real Stripe (customers, Checkout for plans and credit packs, customer portal,
  Stripe Tax, plan → product/price sync, off-session charges for auto top-up). Used when
  ``STRIPE_SECRET_KEY`` is set (test or live keys).
* :class:`SimulatedBilling` — no network. Checkouts open a "test mode" page in the web app; confirming
  produces the same events Stripe would send (``customer.subscription.*``, ``invoice.*``,
  ``checkout.session.completed``) which go through the same webhook handlers in ``services.billing``.

Providers never touch subscription state themselves: they return provider objects or synthetic events
and ``services.billing`` applies them, so both paths share one state machine.
"""

from __future__ import annotations

import abc
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from typing import Any, ClassVar, cast

import stripe
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db.models import Org, Plan, Subscription
from messer_common.db.models.business import SimulatedCheckout
from messer_common.logging import get_logger
from messer_common.plans import CREDIT_PACKS
from messer_common.settings import get_settings

log = get_logger("messer.billing.provider")

SIMULATED_CHECKOUT_TTL = timedelta(hours=24)
INTERVALS = ("month", "year")


class ProviderError(Exception):
    def __init__(self, message: str, *, code: str = "billing_provider_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass(slots=True)
class CheckoutLink:
    id: str
    url: str


@dataclass(slots=True)
class ProviderResult:
    """What a provider call produced: a provider subscription/invoice to apply, or synthetic events."""

    subscription: dict[str, Any] | None = None
    invoice: dict[str, Any] | None = None
    events: list[dict[str, Any]] = field(default_factory=list)


def add_months(value: datetime, months: int) -> datetime:
    """Calendar month arithmetic (day clamped to the target month's length)."""
    month0 = value.month - 1 + months
    year = value.year + month0 // 12
    month = month0 % 12 + 1
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    days = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return value.replace(year=year, month=month, day=min(value.day, days))


def period_end_for(start: datetime, interval: str) -> datetime:
    return add_months(start, 12 if interval == "year" else 1)


def plan_price(plan: Plan, interval: str) -> Decimal:
    return Decimal(plan.price_year_eur if interval == "year" else plan.price_month_eur)


def to_cents(amount: Decimal) -> int:
    return int((Decimal(amount) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def find_pack(pack_id: str | None) -> dict[str, Any] | None:
    return next((p for p in CREDIT_PACKS if p["id"] == pack_id), None)


def pack_label(pack: dict[str, Any], locale: str = "es") -> str:
    credits = f"{int(pack['credits']):,}".replace(",", "." if locale == "es" else ",")
    return f"Paquete de {credits} créditos" if locale == "es" else f"{credits} credits pack"


def _epoch(value: datetime) -> int:
    return int(value.timestamp())


class BillingProvider(abc.ABC):
    mode: ClassVar[str]

    @property
    @abc.abstractmethod
    def test_mode(self) -> bool: ...

    @abc.abstractmethod
    async def ensure_customer(self, *, org: Org, email: str | None, existing: str | None) -> str: ...

    @abc.abstractmethod
    async def subscription_checkout(
        self,
        session: AsyncSession,
        *,
        org: Org,
        plan: Plan,
        interval: str,
        customer_id: str,
        actor_id: uuid.UUID | None,
    ) -> CheckoutLink: ...

    @abc.abstractmethod
    async def pack_checkout(
        self,
        session: AsyncSession,
        *,
        org: Org,
        pack: dict[str, Any],
        customer_id: str,
        actor_id: uuid.UUID | None,
    ) -> CheckoutLink: ...

    @abc.abstractmethod
    async def change_subscription(
        self, *, sub: Subscription, current_plan: Plan, plan: Plan, interval: str
    ) -> ProviderResult: ...

    @abc.abstractmethod
    async def set_cancel_at_period_end(self, *, sub: Subscription, cancel: bool) -> ProviderResult: ...

    @abc.abstractmethod
    async def portal_url(self, *, customer_id: str, return_url: str) -> str: ...

    @abc.abstractmethod
    async def charge_pack(self, *, org: Org, sub: Subscription, pack: dict[str, Any]) -> ProviderResult: ...

    @abc.abstractmethod
    async def sync_plan(self, plan: Plan) -> bool:
        """Create/refresh the provider's product and prices for ``plan``. Returns True if anything changed."""


# ============================================================================= Stripe


def _plain(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return cast(dict[str, Any], obj)
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        return cast(dict[str, Any], to_dict())
    return dict(obj)


class StripeBilling(BillingProvider):
    mode = "stripe"

    def __init__(self, secret_key: str) -> None:
        self._key = secret_key
        self.client = stripe.StripeClient(secret_key, http_client=stripe.HTTPXClient(), max_network_retries=2)

    @property
    def test_mode(self) -> bool:
        return self._key.startswith(("sk_test_", "rk_test_"))

    @staticmethod
    def _urls() -> tuple[str, str]:
        web = get_settings().messer_web_url.rstrip("/")
        return web, f"{web}/app/settings"

    async def _call(self, coro: Any) -> Any:
        try:
            return await coro
        except stripe.CardError as exc:
            raise ProviderError(exc.user_message or "La tarjeta ha sido rechazada.", code="card_declined") from exc
        except stripe.StripeError as exc:
            log.error("stripe.error", error=str(exc), code=getattr(exc, "code", None))
            raise ProviderError(
                exc.user_message or "Stripe no ha podido completar la operación. Inténtalo de nuevo.",
                code="stripe_error",
            ) from exc

    async def ensure_customer(self, *, org: Org, email: str | None, existing: str | None) -> str:
        if existing and not existing.startswith("cus_sim_"):
            return existing
        params: dict[str, Any] = {
            "name": org.name,
            "metadata": {"org_id": str(org.id), "org_slug": org.slug},
            "preferred_locales": ["es", "en"],
        }
        if email:
            params["email"] = email
        customer = await self._call(
            self.client.v1.customers.create_async(
                params=cast(Any, params), options={"idempotency_key": f"customer-{org.id}"}
            )
        )
        return str(customer.id)

    async def _price_id(self, plan: Plan, interval: str) -> str:
        price_id = (plan.stripe_price_ids or {}).get(interval)
        if not price_id:
            await self.sync_plan(plan)
            price_id = (plan.stripe_price_ids or {}).get(interval)
        if not price_id:
            raise ProviderError("El plan no tiene precio configurado en Stripe.", code="price_missing")
        return str(price_id)

    async def subscription_checkout(
        self,
        session: AsyncSession,
        *,
        org: Org,
        plan: Plan,
        interval: str,
        customer_id: str,
        actor_id: uuid.UUID | None,
    ) -> CheckoutLink:
        _, base = self._urls()
        price_id = await self._price_id(plan, interval)
        metadata = {"org_id": str(org.id), "kind": "subscription", "plan_id": plan.id, "interval": interval}
        params: dict[str, Any] = {
            "mode": "subscription",
            "customer": customer_id,
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": f"{base}/billing?checkout=success&session_id={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{base}/billing?checkout=canceled",
            "automatic_tax": {"enabled": True},
            "tax_id_collection": {"enabled": True},
            "customer_update": {"address": "auto", "name": "auto"},
            "billing_address_collection": "required",
            "allow_promotion_codes": True,
            "client_reference_id": str(org.id),
            "locale": "auto",
            "metadata": metadata,
            "subscription_data": {"metadata": metadata},
        }
        s = await self._call(self.client.v1.checkout.sessions.create_async(params=cast(Any, params)))
        return CheckoutLink(id=str(s.id), url=str(s.url))

    async def pack_checkout(
        self,
        session: AsyncSession,
        *,
        org: Org,
        pack: dict[str, Any],
        customer_id: str,
        actor_id: uuid.UUID | None,
    ) -> CheckoutLink:
        _, base = self._urls()
        metadata = {
            "org_id": str(org.id),
            "kind": "credit_pack",
            "pack_id": str(pack["id"]),
            "credits": str(pack["credits"]),
        }
        params: dict[str, Any] = {
            "mode": "payment",
            "customer": customer_id,
            "line_items": [
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": "eur",
                        "unit_amount": to_cents(Decimal(pack["price_eur"])),
                        "tax_behavior": "exclusive",
                        "product_data": {"name": pack_label(pack), "metadata": {"pack_id": str(pack["id"])}},
                    },
                }
            ],
            "success_url": f"{base}/credits?checkout=success&session_id={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{base}/credits?checkout=canceled",
            "automatic_tax": {"enabled": True},
            "tax_id_collection": {"enabled": True},
            "customer_update": {"address": "auto", "name": "auto"},
            "billing_address_collection": "required",
            "client_reference_id": str(org.id),
            "locale": "auto",
            "metadata": metadata,
            # Save the card so auto top-up can charge it later; mirror a VAT invoice for the purchase.
            "payment_intent_data": {"setup_future_usage": "off_session", "metadata": metadata},
            "invoice_creation": {"enabled": True, "invoice_data": {"metadata": {**metadata, "source": "checkout"}}},
        }
        s = await self._call(self.client.v1.checkout.sessions.create_async(params=cast(Any, params)))
        return CheckoutLink(id=str(s.id), url=str(s.url))

    async def change_subscription(
        self, *, sub: Subscription, current_plan: Plan, plan: Plan, interval: str
    ) -> ProviderResult:
        if not sub.stripe_subscription_id:
            raise ProviderError("No hay una suscripción de Stripe activa.", code="no_subscription")
        price_id = await self._price_id(plan, interval)
        current = _plain(await self._call(self.client.v1.subscriptions.retrieve_async(sub.stripe_subscription_id)))
        items = (current.get("items") or {}).get("data") or []
        if not items:
            raise ProviderError("La suscripción de Stripe no tiene conceptos.", code="no_items")
        params: dict[str, Any] = {
            "items": [{"id": items[0]["id"], "price": price_id}],
            "proration_behavior": "always_invoice",
            "cancel_at_period_end": False,
            "metadata": {"org_id": str(sub.org_id), "kind": "subscription", "plan_id": plan.id, "interval": interval},
        }
        updated = await self._call(
            self.client.v1.subscriptions.update_async(sub.stripe_subscription_id, params=cast(Any, params))
        )
        return ProviderResult(subscription=_plain(updated))

    async def set_cancel_at_period_end(self, *, sub: Subscription, cancel: bool) -> ProviderResult:
        if not sub.stripe_subscription_id:
            raise ProviderError("No hay una suscripción de Stripe activa.", code="no_subscription")
        updated = await self._call(
            self.client.v1.subscriptions.update_async(
                sub.stripe_subscription_id, params=cast(Any, {"cancel_at_period_end": cancel})
            )
        )
        return ProviderResult(subscription=_plain(updated))

    async def portal_url(self, *, customer_id: str, return_url: str) -> str:
        portal = await self._call(
            self.client.v1.billing_portal.sessions.create_async(
                params=cast(Any, {"customer": customer_id, "return_url": return_url, "locale": "auto"})
            )
        )
        return str(portal.url)

    async def _default_payment_method(self, sub: Subscription) -> str | None:
        assert sub.stripe_customer_id
        customer = _plain(await self._call(self.client.v1.customers.retrieve_async(sub.stripe_customer_id)))
        pm = (customer.get("invoice_settings") or {}).get("default_payment_method")
        if pm:
            return str(pm if isinstance(pm, str) else pm.get("id"))
        if sub.stripe_subscription_id:
            current = _plain(await self._call(self.client.v1.subscriptions.retrieve_async(sub.stripe_subscription_id)))
            pm = current.get("default_payment_method")
            if pm:
                return str(pm if isinstance(pm, str) else pm.get("id"))
        methods = _plain(
            await self._call(
                self.client.v1.payment_methods.list_async(
                    params=cast(Any, {"customer": sub.stripe_customer_id, "type": "card", "limit": 1})
                )
            )
        )
        data = methods.get("data") or []
        return str(data[0]["id"]) if data else None

    async def charge_pack(self, *, org: Org, sub: Subscription, pack: dict[str, Any]) -> ProviderResult:
        if not sub.stripe_customer_id or sub.stripe_customer_id.startswith("cus_sim_"):
            raise ProviderError("No hay un método de pago guardado.", code="payment_method_required")
        payment_method = await self._default_payment_method(sub)
        if payment_method is None:
            raise ProviderError("No hay un método de pago guardado.", code="payment_method_required")
        metadata = {
            "org_id": str(org.id),
            "kind": "credit_pack",
            "source": "auto_topup",
            "pack_id": str(pack["id"]),
            "credits": str(pack["credits"]),
        }
        draft = await self._call(
            self.client.v1.invoices.create_async(
                params=cast(
                    Any,
                    {
                        "customer": sub.stripe_customer_id,
                        "collection_method": "charge_automatically",
                        "auto_advance": False,
                        "automatic_tax": {"enabled": True},
                        "pending_invoice_items_behavior": "exclude",
                        "description": f"Recarga automática: {pack_label(pack)}",
                        "metadata": metadata,
                    },
                )
            )
        )
        await self._call(
            self.client.v1.invoice_items.create_async(
                params=cast(
                    Any,
                    {
                        "customer": sub.stripe_customer_id,
                        "invoice": draft.id,
                        "currency": "eur",
                        "amount": to_cents(Decimal(pack["price_eur"])),
                        "tax_behavior": "exclusive",
                        "description": pack_label(pack),
                        "metadata": metadata,
                    },
                )
            )
        )
        await self._call(self.client.v1.invoices.finalize_invoice_async(str(draft.id)))
        paid = await self._call(
            self.client.v1.invoices.pay_async(str(draft.id), params=cast(Any, {"payment_method": payment_method}))
        )
        return ProviderResult(invoice=_plain(paid))

    async def sync_plan(self, plan: Plan) -> bool:
        changed = False
        product_params: dict[str, Any] = {
            "name": f"Messer {plan.name}",
            "description": plan.description or plan.name,
            "metadata": {"plan_id": plan.id},
        }
        product_id = plan.stripe_product_id
        if product_id:
            try:
                await self.client.v1.products.update_async(
                    product_id, params=cast(Any, {**product_params, "active": True})
                )
            except stripe.InvalidRequestError:
                product_id = None
        if not product_id:
            product = await self._call(
                self.client.v1.products.create_async(
                    params=cast(Any, {**product_params, "id": f"messer_{plan.id}_{uuid.uuid4().hex[:6]}"})
                )
            )
            product_id = str(product.id)
            plan.stripe_product_id = product_id
            changed = True
        price_ids = dict(plan.stripe_price_ids or {})
        for interval in INTERVALS:
            cents = to_cents(plan_price(plan, interval))
            old_id = price_ids.get(interval)
            if old_id:
                try:
                    price = _plain(await self.client.v1.prices.retrieve_async(str(old_id)))
                except stripe.InvalidRequestError:
                    price = {}
                recurring = price.get("recurring") or {}
                if (
                    price.get("active")
                    and price.get("unit_amount") == cents
                    and price.get("currency") == "eur"
                    and recurring.get("interval") == interval
                    and price.get("product") == product_id
                ):
                    continue
            created = await self._call(
                self.client.v1.prices.create_async(
                    params=cast(
                        Any,
                        {
                            "product": product_id,
                            "currency": "eur",
                            "unit_amount": cents,
                            "recurring": {"interval": interval},
                            "tax_behavior": "exclusive",
                            "lookup_key": f"messer_{plan.id}_{interval}",
                            "transfer_lookup_key": True,
                            "metadata": {"plan_id": plan.id, "interval": interval},
                        },
                    )
                )
            )
            price_ids[interval] = str(created.id)
            changed = True
            if old_id:
                try:
                    await self.client.v1.prices.update_async(str(old_id), params=cast(Any, {"active": False}))
                except stripe.StripeError as exc:
                    log.warning("stripe.price_archive_failed", price=old_id, error=str(exc))
        if changed:
            plan.stripe_price_ids = price_ids
        return changed


# ============================================================================= simulated


def _event(event_type: str, obj: dict[str, Any], now: datetime) -> dict[str, Any]:
    return {
        "id": f"evt_sim_{uuid.uuid4().hex}",
        "object": "event",
        "type": event_type,
        "livemode": False,
        "created": _epoch(now),
        "data": {"object": obj},
    }


class SimulatedBilling(BillingProvider):
    """Stripe test mode without keys: no network, same event shapes as Stripe."""

    mode = "simulated"

    @property
    def test_mode(self) -> bool:
        return True

    # ---------------------------------------------------------------- object builders
    @staticmethod
    def price_id(plan_id: str, interval: str) -> str:
        return f"price_sim_{plan_id}_{interval}"

    def subscription_object(
        self,
        *,
        sub_id: str,
        customer_id: str,
        org_id: uuid.UUID,
        plan_id: str,
        interval: str,
        status: str,
        period_start: datetime,
        period_end: datetime,
        cancel_at_period_end: bool = False,
        canceled_at: datetime | None = None,
    ) -> dict[str, Any]:
        metadata = {"org_id": str(org_id), "kind": "subscription", "plan_id": plan_id, "interval": interval}
        return {
            "id": sub_id,
            "object": "subscription",
            "customer": customer_id,
            "status": status,
            "livemode": False,
            "metadata": metadata,
            "cancel_at_period_end": cancel_at_period_end,
            "canceled_at": _epoch(canceled_at) if canceled_at else None,
            "ended_at": _epoch(canceled_at) if canceled_at and status == "canceled" else None,
            "current_period_start": _epoch(period_start),
            "current_period_end": _epoch(period_end),
            "items": {
                "data": [
                    {
                        "id": f"si_sim_{sub_id[-12:]}",
                        "price": {
                            "id": self.price_id(plan_id, interval),
                            "currency": "eur",
                            "recurring": {"interval": interval},
                            "metadata": {"plan_id": plan_id, "interval": interval},
                        },
                        "current_period_start": _epoch(period_start),
                        "current_period_end": _epoch(period_end),
                    }
                ]
            },
        }

    def invoice_object(
        self,
        *,
        org_id: uuid.UUID,
        customer_id: str,
        amount: Decimal,
        description: str,
        status: str = "paid",
        sub_id: str | None = None,
        billing_reason: str = "manual",
        plan_id: str | None = None,
        interval: str | None = None,
        period_start: datetime,
        period_end: datetime,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        cents = to_cents(amount)
        invoice_id = f"in_sim_{uuid.uuid4().hex[:24]}"
        line: dict[str, Any] = {
            "id": f"il_sim_{uuid.uuid4().hex[:16]}",
            "amount": cents,
            "description": description,
            "period": {"start": _epoch(period_start), "end": _epoch(period_end)},
            "metadata": {"plan_id": plan_id or "", "interval": interval or ""},
        }
        if plan_id and interval:
            line["price"] = {"id": self.price_id(plan_id, interval), "recurring": {"interval": interval}}
        paid = status == "paid"
        return {
            "id": invoice_id,
            "object": "invoice",
            "customer": customer_id,
            "subscription": sub_id,
            "billing_reason": billing_reason,
            "number": f"SIM-{period_start:%Y%m}-{invoice_id[-6:].upper()}",
            "status": status,
            "currency": "eur",
            "amount_due": cents,
            "amount_paid": cents if paid else 0,
            "total": cents,
            "tax": 0,
            "hosted_invoice_url": None,
            "invoice_pdf": None,
            "period_start": _epoch(period_start),
            "period_end": _epoch(period_end),
            "livemode": False,
            "metadata": {"org_id": str(org_id), **(metadata or {})},
            "lines": {"data": [line]},
        }

    # ---------------------------------------------------------------- provider API
    async def ensure_customer(self, *, org: Org, email: str | None, existing: str | None) -> str:
        return existing or f"cus_sim_{uuid.uuid4().hex[:14]}"

    async def _checkout(
        self,
        session: AsyncSession,
        *,
        org: Org,
        kind: str,
        amount: Decimal,
        actor_id: uuid.UUID | None,
        plan_id: str | None = None,
        interval: str | None = None,
        pack_id: str | None = None,
        customer_id: str,
    ) -> CheckoutLink:
        checkout = SimulatedCheckout(
            org_id=org.id,
            kind=kind,
            plan_id=plan_id,
            interval=interval,
            pack_id=pack_id,
            amount_eur=amount,
            status="open",
            created_by=actor_id,
            expires_at=datetime.now(UTC) + SIMULATED_CHECKOUT_TTL,
            result={"customer_id": customer_id},
        )
        session.add(checkout)
        await session.flush()
        web = get_settings().messer_web_url.rstrip("/")
        return CheckoutLink(id=str(checkout.id), url=f"{web}/app/settings/billing/checkout/{checkout.id}")

    async def subscription_checkout(
        self,
        session: AsyncSession,
        *,
        org: Org,
        plan: Plan,
        interval: str,
        customer_id: str,
        actor_id: uuid.UUID | None,
    ) -> CheckoutLink:
        return await self._checkout(
            session,
            org=org,
            kind="subscription",
            amount=plan_price(plan, interval),
            actor_id=actor_id,
            plan_id=plan.id,
            interval=interval,
            customer_id=customer_id,
        )

    async def pack_checkout(
        self,
        session: AsyncSession,
        *,
        org: Org,
        pack: dict[str, Any],
        customer_id: str,
        actor_id: uuid.UUID | None,
    ) -> CheckoutLink:
        return await self._checkout(
            session,
            org=org,
            kind="credit_pack",
            amount=Decimal(pack["price_eur"]),
            actor_id=actor_id,
            pack_id=str(pack["id"]),
            customer_id=customer_id,
        )

    def checkout_events(self, checkout: SimulatedCheckout, *, sub: Subscription | None) -> list[dict[str, Any]]:
        """Events Stripe sends when a Checkout Session completes (subscription or one-off pack)."""
        now = datetime.now(UTC)
        customer_id = (sub.stripe_customer_id if sub else None) or str(
            (checkout.result or {}).get("customer_id") or f"cus_sim_{uuid.uuid4().hex[:14]}"
        )
        session_obj: dict[str, Any] = {
            "id": f"cs_sim_{checkout.id.hex}",
            "object": "checkout.session",
            "customer": customer_id,
            "client_reference_id": str(checkout.org_id),
            "status": "complete",
            "payment_status": "paid",
            "amount_total": to_cents(Decimal(checkout.amount_eur)),
            "currency": "eur",
            "livemode": False,
        }
        if checkout.kind == "credit_pack":
            pack = find_pack(checkout.pack_id)
            if pack is None:
                raise ProviderError("El paquete de créditos ya no existe.", code="unknown_pack")
            metadata = {
                "org_id": str(checkout.org_id),
                "kind": "credit_pack",
                "pack_id": str(pack["id"]),
                "credits": str(pack["credits"]),
            }
            session_obj.update(mode="payment", metadata=metadata, subscription=None)
            invoice = self.invoice_object(
                org_id=checkout.org_id,
                customer_id=customer_id,
                amount=Decimal(checkout.amount_eur),
                description=pack_label(pack),
                period_start=now,
                period_end=now,
                metadata={**metadata, "source": "checkout"},
            )
            return [_event("checkout.session.completed", session_obj, now), _event("invoice.paid", invoice, now)]

        assert checkout.plan_id and checkout.interval
        sub_id = f"sub_sim_{uuid.uuid4().hex[:20]}"
        period_end = period_end_for(now, checkout.interval)
        metadata = {
            "org_id": str(checkout.org_id),
            "kind": "subscription",
            "plan_id": checkout.plan_id,
            "interval": checkout.interval,
        }
        session_obj.update(mode="subscription", subscription=sub_id, metadata=metadata)
        subscription = self.subscription_object(
            sub_id=sub_id,
            customer_id=customer_id,
            org_id=checkout.org_id,
            plan_id=checkout.plan_id,
            interval=checkout.interval,
            status="active",
            period_start=now,
            period_end=period_end,
        )
        invoice = self.invoice_object(
            org_id=checkout.org_id,
            customer_id=customer_id,
            amount=Decimal(checkout.amount_eur),
            description=f"Messer {checkout.plan_id}",
            sub_id=sub_id,
            billing_reason="subscription_create",
            plan_id=checkout.plan_id,
            interval=checkout.interval,
            period_start=now,
            period_end=period_end,
        )
        return [
            _event("checkout.session.completed", session_obj, now),
            _event("customer.subscription.created", subscription, now),
            _event("invoice.paid", invoice, now),
        ]

    def _sub_object_from(self, sub: Subscription, **overrides: Any) -> dict[str, Any]:
        assert sub.stripe_subscription_id and sub.stripe_customer_id
        now = datetime.now(UTC)
        start = sub.current_period_start or now
        args: dict[str, Any] = {
            "sub_id": sub.stripe_subscription_id,
            "customer_id": sub.stripe_customer_id,
            "org_id": sub.org_id,
            "plan_id": sub.plan_id,
            "interval": sub.interval,
            "status": sub.status,
            "period_start": start,
            "period_end": sub.current_period_end or period_end_for(start, sub.interval),
            "cancel_at_period_end": sub.cancel_at_period_end,
            "canceled_at": sub.canceled_at,
        }
        args.update(overrides)
        return self.subscription_object(**args)

    async def change_subscription(
        self, *, sub: Subscription, current_plan: Plan, plan: Plan, interval: str
    ) -> ProviderResult:
        if not sub.stripe_subscription_id or not sub.stripe_customer_id:
            raise ProviderError("No hay una suscripción activa.", code="no_subscription")
        now = datetime.now(UTC)
        start = sub.current_period_start or now
        end = sub.current_period_end or period_end_for(start, sub.interval)
        total = max((end - start).total_seconds(), 1.0)
        remaining = Decimal(str(max(0.0, min(1.0, (end - now).total_seconds() / total))))
        old_price = plan_price(current_plan, sub.interval)
        new_price = plan_price(plan, interval)
        events: list[dict[str, Any]] = []
        if interval != sub.interval:
            # Changing the billing interval starts a new period now, crediting the unused time.
            new_start, new_end = now, period_end_for(now, interval)
            amount = max(Decimal("0"), new_price - (old_price * remaining)).quantize(Decimal("0.01"))
        else:
            new_start, new_end = start, end
            amount = max(Decimal("0"), (new_price - old_price) * remaining).quantize(Decimal("0.01"))
        subscription = self._sub_object_from(
            sub,
            plan_id=plan.id,
            interval=interval,
            status="active" if sub.status in ("active", "past_due") else sub.status,
            period_start=new_start,
            period_end=new_end,
            cancel_at_period_end=False,
            canceled_at=None,
        )
        events.append(_event("customer.subscription.updated", subscription, now))
        if amount > 0 or interval != sub.interval:
            invoice = self.invoice_object(
                org_id=sub.org_id,
                customer_id=sub.stripe_customer_id,
                amount=amount,
                description=f"Cambio a Messer {plan.name}",
                sub_id=sub.stripe_subscription_id,
                billing_reason="subscription_update",
                plan_id=plan.id,
                interval=interval,
                period_start=now if interval == sub.interval else new_start,
                period_end=new_end,
            )
            events.append(_event("invoice.paid", invoice, now))
        return ProviderResult(events=events)

    async def set_cancel_at_period_end(self, *, sub: Subscription, cancel: bool) -> ProviderResult:
        if not sub.stripe_subscription_id:
            raise ProviderError("No hay una suscripción activa.", code="no_subscription")
        now = datetime.now(UTC)
        obj = self._sub_object_from(sub, cancel_at_period_end=cancel, canceled_at=now if cancel else None)
        return ProviderResult(events=[_event("customer.subscription.updated", obj, now)])

    async def portal_url(self, *, customer_id: str, return_url: str) -> str:
        raise ProviderError(
            "El portal de cliente de Stripe no está disponible en modo de prueba. Gestiona el plan desde esta página.",
            code="portal_unavailable",
        )

    async def charge_pack(self, *, org: Org, sub: Subscription, pack: dict[str, Any]) -> ProviderResult:
        if not sub.stripe_customer_id:
            raise ProviderError("No hay un método de pago guardado.", code="payment_method_required")
        now = datetime.now(UTC)
        invoice = self.invoice_object(
            org_id=org.id,
            customer_id=sub.stripe_customer_id,
            amount=Decimal(pack["price_eur"]),
            description=f"Recarga automática: {pack_label(pack)}",
            period_start=now,
            period_end=now,
            metadata={
                "kind": "credit_pack",
                "source": "auto_topup",
                "pack_id": str(pack["id"]),
                "credits": str(pack["credits"]),
            },
        )
        return ProviderResult(events=[_event("invoice.paid", invoice, now)])

    def renewal_events(self, sub: Subscription, now: datetime) -> list[dict[str, Any]]:
        """What Stripe sends at the end of a billing period (renewal, or deletion if canceling)."""
        assert sub.stripe_subscription_id and sub.stripe_customer_id and sub.current_period_end
        if sub.cancel_at_period_end:
            obj = self._sub_object_from(sub, status="canceled", canceled_at=sub.current_period_end)
            return [_event("customer.subscription.deleted", obj, now)]
        start = sub.current_period_end
        end = period_end_for(start, sub.interval)
        obj = self._sub_object_from(sub, period_start=start, period_end=end)
        return [_event("customer.subscription.updated", obj, now)]

    def renewal_invoice_event(
        self, sub: Subscription, plan: Plan, *, paid: bool = True, billing_reason: str = "subscription_cycle"
    ) -> dict[str, Any]:
        """``invoice.paid`` (or ``invoice.payment_failed``) for the subscription's current period."""
        assert sub.stripe_subscription_id and sub.stripe_customer_id
        now = datetime.now(UTC)
        start = sub.current_period_start or now
        end = sub.current_period_end or period_end_for(start, sub.interval)
        invoice = self.invoice_object(
            org_id=sub.org_id,
            customer_id=sub.stripe_customer_id,
            amount=plan_price(plan, sub.interval),
            description=f"Messer {plan.name}",
            status="paid" if paid else "open",
            sub_id=sub.stripe_subscription_id,
            billing_reason=billing_reason,
            plan_id=plan.id,
            interval=sub.interval,
            period_start=start,
            period_end=end,
        )
        return _event("invoice.paid" if paid else "invoice.payment_failed", invoice, now)

    async def sync_plan(self, plan: Plan) -> bool:
        return False


@lru_cache(maxsize=1)
def _provider_for(secret_key: str) -> BillingProvider:
    return StripeBilling(secret_key) if secret_key else SimulatedBilling()


def get_billing_provider() -> BillingProvider:
    """Stripe when ``STRIPE_SECRET_KEY`` is set, the simulated test mode otherwise."""
    return _provider_for(get_settings().stripe_secret_key)
