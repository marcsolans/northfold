"use server";

import { type ActionResult, fail, ok } from "@/lib/action-result";
import { validateCartSchema } from "@/lib/validators/cart";
import { runAction } from "@/server/action";
import { type CartValidation, validateCartLines } from "@/server/cart";

/** Public (guest carts are allowed): re-validates the browser cart against live data. */
export async function validateCart(input: unknown): Promise<ActionResult<CartValidation>> {
  return runAction("validateCart", async () => {
    const parsed = validateCartSchema.safeParse(input);
    if (!parsed.success) return fail("Your bag could not be read. Please refresh the page.");
    // Merge duplicate lines defensively (a corrupted localStorage entry should not break the page).
    const merged = new Map<string, (typeof parsed.data)[number]>();
    for (const line of parsed.data) {
      const existing = merged.get(line.variantId);
      merged.set(
        line.variantId,
        existing ? { ...line, quantity: existing.quantity + line.quantity } : line,
      );
    }
    return ok(await validateCartLines([...merged.values()]));
  });
}
