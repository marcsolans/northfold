import { type ReactNode } from "react";

import { amountUntilFreeShipping } from "@/lib/pricing";
import { formatMoney, type MoneyInput, money } from "@/lib/money";
import { PRICING } from "@/lib/store-config";

export interface SummaryTotals {
  subtotal: MoneyInput;
  shippingFee: MoneyInput;
  tax: MoneyInput;
  total: MoneyInput;
}

function Row({
  label,
  value,
  strong = false,
}: {
  label: ReactNode;
  value: ReactNode;
  strong?: boolean;
}) {
  return (
    <div
      className={
        strong ? "flex justify-between text-base font-medium" : "flex justify-between text-sm"
      }
    >
      <dt className={strong ? "" : "text-muted-foreground"}>{label}</dt>
      <dd className="tabular-nums">{value}</dd>
    </div>
  );
}

/** Subtotal / shipping / tax / total. Used by the cart, checkout and order pages. */
export function OrderSummary({
  totals,
  showFreeShippingHint = false,
  children,
}: {
  totals: SummaryTotals;
  showFreeShippingHint?: boolean;
  children?: ReactNode;
}) {
  const remaining = amountUntilFreeShipping(totals.subtotal);
  const progress = Math.min(
    100,
    money(totals.subtotal).dividedBy(PRICING.freeShippingThreshold).times(100).toNumber(),
  );
  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <h2 className="text-base font-medium">Order summary</h2>
      {showFreeShippingHint && money(totals.subtotal).greaterThan(0) ? (
        <div className="mt-4">
          <p className="text-sm text-muted-foreground">
            {remaining.isZero()
              ? "Your order ships free."
              : `Add ${formatMoney(remaining)} more for free shipping.`}
          </p>
          <div className="mt-2 h-1 overflow-hidden rounded-full bg-surface" aria-hidden="true">
            <div
              className="h-full rounded-full bg-accent transition-all"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      ) : null}
      <dl className="mt-5 space-y-3">
        <Row label="Subtotal" value={formatMoney(totals.subtotal)} />
        <Row
          label="Shipping"
          value={money(totals.shippingFee).isZero() ? "Free" : formatMoney(totals.shippingFee)}
        />
        <Row label="Tax" value={formatMoney(totals.tax)} />
        <div className="border-t border-border pt-3">
          <Row label="Total" value={formatMoney(totals.total)} strong />
        </div>
      </dl>
      {children ? <div className="mt-6">{children}</div> : null}
    </div>
  );
}
