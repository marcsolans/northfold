import { formatEur, localeTag } from "@/lib/format";

import type { PublicPlan } from "./public-api";

export function eur(value: number | string, locale: string, fractionDigits?: number): string {
  const n = Number(value);
  const digits = fractionDigits ?? (Number.isInteger(n) ? 0 : 2);
  return formatEur(n, localeTag(locale), digits);
}

/** Annual price expressed per month (e.g. 1990/12 → 165.83). */
export function monthlyEquivalent(plan: PublicPlan): number {
  return Number(plan.price_year_eur) / 12;
}

/** Yearly saving of the annual price against 12 monthly payments (never negative). */
export function annualSaving(plan: PublicPlan): number {
  return Math.max(0, Number(plan.price_month_eur) * 12 - Number(plan.price_year_eur));
}

/** Discount of the annual price, as a whole percentage. */
export function annualDiscountPct(plan: PublicPlan): number {
  const monthly = Number(plan.price_month_eur) * 12;
  if (monthly <= 0) return 0;
  return Math.round((annualSaving(plan) / monthly) * 100);
}

export function maxAnnualDiscountPct(plans: PublicPlan[]): number {
  return plans.reduce((max, p) => Math.max(max, annualDiscountPct(p)), 0);
}

/** Schema.org offers built from the live plans. */
export function planOffers(plans: PublicPlan[], url: string): Record<string, unknown>[] {
  return plans.map((plan) => ({
    "@type": "Offer",
    name: plan.name,
    description: plan.description,
    url,
    priceCurrency: "EUR",
    price: Number(plan.price_month_eur).toFixed(2),
    priceSpecification: {
      "@type": "UnitPriceSpecification",
      price: Number(plan.price_month_eur).toFixed(2),
      priceCurrency: "EUR",
      unitCode: "MON",
      valueAddedTaxIncluded: false,
      ...(plan.price_is_starting ? { minPrice: Number(plan.price_month_eur).toFixed(2) } : {}),
    },
  }));
}
