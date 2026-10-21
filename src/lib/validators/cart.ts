import { z } from "zod";

import { CATALOG } from "../store-config";

import { idSchema, moneyStringSchema } from "./common";

export const cartLineSchema = z.object({
  variantId: idSchema,
  quantity: z.number().int().min(1).max(CATALOG.maxQuantityPerLine),
});
export type CartLineInput = z.infer<typeof cartLineSchema>;

export const cartLinesSchema = z
  .array(cartLineSchema)
  .max(50, { error: "Your cart has too many items" })
  .refine((lines) => new Set(lines.map((l) => l.variantId)).size === lines.length, {
    error: "Duplicate cart lines",
  });

/**
 * What the browser sends to have its cart re-validated. `knownPrice` and `label` come from the
 * display snapshot and are used only to describe changes to the user — never for pricing.
 */
export const validateCartSchema = z
  .array(
    cartLineSchema.extend({
      // Quantities are clamped, not rejected, when re-validating a stale cart.
      quantity: z.number().int().min(1).max(1000),
      knownPrice: moneyStringSchema.optional(),
      label: z.string().trim().max(200).optional(),
    }),
  )
  .max(50);
export type ValidateCartInput = z.input<typeof validateCartSchema>;
