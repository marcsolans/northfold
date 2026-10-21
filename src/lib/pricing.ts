import { lineTotal, money, type Money, type MoneyInput, roundToCents, sumMoney } from "./money";
import { PRICING } from "./store-config";

export interface PricedLine {
  unitPrice: MoneyInput;
  quantity: number;
}

export interface OrderTotals {
  subtotal: Money;
  shippingFee: Money;
  tax: Money;
  total: Money;
}

export function calculateShipping(subtotal: MoneyInput): Money {
  const amount = money(subtotal);
  if (amount.isZero()) return money(0);
  return amount.greaterThanOrEqualTo(PRICING.freeShippingThreshold)
    ? money(0)
    : money(PRICING.flatShippingFee);
}

export function calculateTax(subtotal: MoneyInput): Money {
  return roundToCents(money(subtotal).times(PRICING.taxRate));
}

/** Totals for a set of lines. Used by the cart (display) and by the server (authoritative). */
export function calculateTotals(lines: readonly PricedLine[]): OrderTotals {
  const subtotal = roundToCents(sumMoney(lines.map((l) => lineTotal(l.unitPrice, l.quantity))));
  const shippingFee = calculateShipping(subtotal);
  const tax = calculateTax(subtotal);
  return { subtotal, shippingFee, tax, total: subtotal.plus(shippingFee).plus(tax) };
}

/** How much more the customer needs to spend to unlock free shipping (zero when unlocked). */
export function amountUntilFreeShipping(subtotal: MoneyInput): Money {
  const remaining = money(PRICING.freeShippingThreshold).minus(money(subtotal));
  return remaining.isNegative() ? money(0) : remaining;
}
