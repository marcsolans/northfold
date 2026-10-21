/**
 * Store-wide business constants. Change them here and every price calculation,
 * label and email follows.
 */
export const STORE = {
  name: "Northfold",
  tagline: "Minimal, well-made clothing for men, women and children",
  description:
    "Northfold makes minimal, well-made clothing for men, women and children: considered essentials in natural fabrics and quiet colours, designed to be worn for years.",
  currency: "usd",
  locale: "en-US",
  supportEmail: "hello@northfold.shop",
} as const;

export const PRICING = {
  /** Flat shipping fee in dollars, charged below the free-shipping threshold. */
  flatShippingFee: "10.00",
  /** Orders with a subtotal at or above this amount ship for free. */
  freeShippingThreshold: "100.00",
  /** Sales tax rate applied to the subtotal (0.08 = 8%). */
  taxRate: "0",
} as const;

export const CATALOG = {
  pageSize: 12,
  lowStockThreshold: 5,
  maxQuantityPerLine: 10,
} as const;

export const STRIPE_CHECKOUT_TTL_MINUTES = 30;
