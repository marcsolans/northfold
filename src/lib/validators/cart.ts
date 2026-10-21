import { z } from "zod";

import { CATALOG } from "../store-config";

import { idSchema } from "./common";

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
