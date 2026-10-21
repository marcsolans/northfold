import "server-only";

import type { Size } from "@/generated/prisma/enums";
import { type MoneyString, toMoneyString } from "@/lib/money";
import { prisma } from "@/lib/prisma";
import { CATALOG } from "@/lib/store-config";

export interface CartLineSnapshot {
  productId: string;
  productName: string;
  productSlug: string;
  imageUrl: string | null;
  size: Size;
  colorName: string;
  unitPrice: MoneyString;
  available: number;
}

export interface ValidatedCartLine {
  variantId: string;
  quantity: number;
  snapshot: CartLineSnapshot;
}

export type CartChange =
  | { type: "removed"; label: string; reason: "unavailable" | "sold_out" }
  | { type: "quantity_reduced"; label: string; from: number; to: number }
  | { type: "price_changed"; label: string; from: MoneyString; to: MoneyString };

export interface CartValidation {
  lines: ValidatedCartLine[];
  changes: CartChange[];
}

interface LineToValidate {
  variantId: string;
  quantity: number;
  knownPrice?: string;
  label?: string;
}

/** Loads variants with the product data a cart line needs. */
export async function loadCartVariants(variantIds: readonly string[]) {
  const variants = await prisma.productVariant.findMany({
    where: { id: { in: [...variantIds] } },
    include: {
      product: {
        select: {
          id: true,
          name: true,
          slug: true,
          price: true,
          isArchived: true,
          images: { orderBy: { position: "asc" }, take: 1, select: { url: true } },
        },
      },
    },
  });
  return new Map(variants.map((variant) => [variant.id, variant]));
}

/**
 * Re-validates a browser cart against the database: drops unavailable or sold-out items,
 * clamps quantities to stock, and refreshes prices. Every adjustment is reported so the UI can
 * tell the customer what changed.
 */
export async function validateCartLines(lines: readonly LineToValidate[]): Promise<CartValidation> {
  const variants = await loadCartVariants(lines.map((line) => line.variantId));
  const validated: ValidatedCartLine[] = [];
  const changes: CartChange[] = [];

  for (const line of lines) {
    const variant = variants.get(line.variantId);
    const fallbackLabel = line.label ?? "An item in your bag";
    if (!variant || variant.product.isArchived) {
      changes.push({ type: "removed", label: fallbackLabel, reason: "unavailable" });
      continue;
    }
    const label = `${variant.product.name} (${variant.size} / ${variant.colorName})`;
    if (variant.stock <= 0) {
      changes.push({ type: "removed", label, reason: "sold_out" });
      continue;
    }

    const quantity = Math.min(line.quantity, variant.stock, CATALOG.maxQuantityPerLine);
    if (quantity < line.quantity) {
      changes.push({ type: "quantity_reduced", label, from: line.quantity, to: quantity });
    }
    const unitPrice = toMoneyString(variant.product.price);
    if (line.knownPrice !== undefined && toMoneyString(line.knownPrice) !== unitPrice) {
      changes.push({
        type: "price_changed",
        label,
        from: toMoneyString(line.knownPrice),
        to: unitPrice,
      });
    }

    validated.push({
      variantId: variant.id,
      quantity,
      snapshot: {
        productId: variant.product.id,
        productName: variant.product.name,
        productSlug: variant.product.slug,
        imageUrl: variant.product.images[0]?.url ?? null,
        size: variant.size,
        colorName: variant.colorName,
        unitPrice,
        available: variant.stock,
      },
    });
  }

  return { lines: validated, changes };
}
