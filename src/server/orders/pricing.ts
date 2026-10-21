import "server-only";

import type { Size } from "@/generated/prisma/enums";
import { lineTotal, type MoneyString, toMoneyString } from "@/lib/money";
import { calculateTotals } from "@/lib/pricing";
import type { CartLineInput } from "@/lib/validators/cart";
import { loadCartVariants } from "@/server/cart";

import { UserFacingError } from "../action";

export interface PricedOrderLine {
  variantId: string;
  quantity: number;
  unitPrice: MoneyString;
  lineTotal: MoneyString;
  label: string;
  stock: number;
  snapshot: {
    productName: string;
    productSlug: string;
    imageUrl: string | null;
    size: Size;
    colorName: string;
    sku: string;
  };
}

export interface PricedOrder {
  lines: PricedOrderLine[];
  subtotal: MoneyString;
  shippingFee: MoneyString;
  tax: MoneyString;
  total: MoneyString;
}

/**
 * Prices an order from the database only: the client sends variant ids and quantities, never
 * prices. Fails with a user-facing message when a product is unavailable.
 */
export async function priceOrder(items: readonly CartLineInput[]): Promise<PricedOrder> {
  const variants = await loadCartVariants(items.map((item) => item.variantId));
  const unavailable: string[] = [];
  const lines: PricedOrderLine[] = [];

  for (const item of items) {
    const variant = variants.get(item.variantId);
    if (!variant || variant.product.isArchived) {
      unavailable.push("an item in your bag");
      continue;
    }
    const unitPrice = toMoneyString(variant.product.price);
    lines.push({
      variantId: variant.id,
      quantity: item.quantity,
      unitPrice,
      lineTotal: toMoneyString(lineTotal(unitPrice, item.quantity)),
      label: `${variant.product.name} (${variant.size} / ${variant.colorName})`,
      stock: variant.stock,
      snapshot: {
        productName: variant.product.name,
        productSlug: variant.product.slug,
        imageUrl: variant.product.images[0]?.url ?? null,
        size: variant.size,
        colorName: variant.colorName,
        sku: variant.sku,
      },
    });
  }

  if (unavailable.length > 0) {
    throw new UserFacingError(
      "Some items in your bag are no longer available. Please review your bag.",
    );
  }

  const totals = calculateTotals(lines);
  return {
    lines,
    subtotal: toMoneyString(totals.subtotal),
    shippingFee: toMoneyString(totals.shippingFee),
    tax: toMoneyString(totals.tax),
    total: toMoneyString(totals.total),
  };
}
