import DecimalJs from "decimal.js";

import { STORE } from "./store-config";

/**
 * Decimal constructor dedicated to money: high precision, banker-free half-up rounding.
 * A clone keeps the global decimal.js configuration untouched.
 */
export const Money = DecimalJs.clone({ precision: 28, rounding: DecimalJs.ROUND_HALF_UP });
export type Money = InstanceType<typeof Money>;

/** Anything that can represent an amount: numbers, strings, decimal.js or Prisma Decimals. */
export type MoneyInput = number | string | { toString(): string };

export function money(value: MoneyInput): Money {
  const parsed = new Money(typeof value === "number" ? value : value.toString());
  if (!parsed.isFinite()) {
    throw new RangeError(`Invalid money amount: ${String(value)}`);
  }
  return parsed;
}

export function sumMoney(values: readonly MoneyInput[]): Money {
  return values.reduce<Money>((total, value) => total.plus(money(value)), money(0));
}

export function lineTotal(unitPrice: MoneyInput, quantity: number): Money {
  if (!Number.isInteger(quantity) || quantity < 0) {
    throw new RangeError(`Quantity must be a non-negative integer, got ${quantity}`);
  }
  return money(unitPrice).times(quantity);
}

/** Rounds to whole cents (half-up). */
export function roundToCents(value: MoneyInput): Money {
  return money(value).toDecimalPlaces(2, Money.ROUND_HALF_UP);
}

/** Integer minor units for Stripe. Only call this at the Stripe boundary. */
export function toCents(value: MoneyInput): number {
  return roundToCents(value).times(100).toNumber();
}

export function fromCents(cents: number): Money {
  if (!Number.isInteger(cents)) {
    throw new RangeError(`Cents must be an integer, got ${cents}`);
  }
  return money(cents).dividedBy(100);
}

/** A string that holds a decimal number, e.g. "19.90". */
export type MoneyString = `${number}`;

/** Fixed two-decimal string, the serialisable form used across the server/client boundary. */
export function toMoneyString(value: MoneyInput): MoneyString {
  // toFixed on a finite decimal always yields a numeric literal.
  return roundToCents(value).toFixed(2) as MoneyString;
}

const formatter = new Intl.NumberFormat(STORE.locale, {
  style: "currency",
  currency: STORE.currency.toUpperCase(),
});

export function formatMoney(value: MoneyInput): string {
  // Intl formats numeric strings exactly, so no float conversion happens here.
  return formatter.format(toMoneyString(value));
}
