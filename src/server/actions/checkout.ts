"use server";

import { revalidateTag } from "next/cache";

import { type ActionResult, fail, ok } from "@/lib/action-result";
import { CACHE_TAGS } from "@/lib/cache-tags";
import { RATE_LIMITS } from "@/lib/store-config";
import { placeOrderSchema } from "@/lib/validators/checkout";
import { fieldErrorsFrom } from "@/lib/validators/common";
import { runAction } from "@/server/action";
import { requireUser } from "@/server/auth/session";
import { type PlaceOrderResult, placeOrderForUser } from "@/server/orders/place-order";
import { consumeRateLimit } from "@/server/rate-limit";

/**
 * Places an order. Prices, totals and stock come from the database; the client only sends
 * variant ids, quantities, the shipping choice and the payment method.
 */
export async function placeOrder(input: unknown): Promise<ActionResult<PlaceOrderResult>> {
  return runAction("placeOrder", async () => {
    const user = await requireUser();

    const limit = await consumeRateLimit(`place-order:${user.id}`, RATE_LIMITS.placeOrder);
    if (!limit.allowed) {
      return fail(
        `Too many checkout attempts. Please wait ${limit.retryAfter} seconds and try again.`,
      );
    }

    const parsed = placeOrderSchema.safeParse(input);
    if (!parsed.success) {
      return fail("Please check your details and try again.", fieldErrorsFrom(parsed.error));
    }

    const result = await placeOrderForUser(user, parsed.data);
    // Stock may have changed: refresh catalog pages in the background.
    revalidateTag(CACHE_TAGS.products, "max");
    return ok(result);
  });
}
