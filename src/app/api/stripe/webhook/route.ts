import { revalidateTag } from "next/cache";
import Stripe from "stripe";

import { env } from "@/env";
import { CACHE_TAGS } from "@/lib/cache-tags";
import { logger } from "@/lib/logger";
import { processStripeEvent } from "@/server/stripe/webhook";

/**
 * Stripe webhook. Local testing:
 *   stripe listen --api-key "$STRIPE_SECRET_KEY" --forward-to localhost:3000/api/stripe/webhook
 */
export async function POST(request: Request): Promise<Response> {
  const secret = env.STRIPE_WEBHOOK_SECRET;
  if (!secret) {
    logger.error("Stripe webhook called but STRIPE_WEBHOOK_SECRET is not configured");
    return new Response("Webhooks are not configured", { status: 503 });
  }

  const signature = request.headers.get("stripe-signature");
  if (!signature) return new Response("Missing Stripe-Signature header", { status: 400 });

  // The signature covers the exact raw bytes, so the body must not be parsed first.
  const payload = await request.text();
  let event: Stripe.Event;
  try {
    event = Stripe.webhooks.constructEvent(payload, signature, secret);
  } catch (error) {
    logger.warn("Rejected Stripe webhook with an invalid signature", {
      error: error instanceof Error ? error.message : String(error),
    });
    return new Response("Invalid signature", { status: 400 });
  }

  try {
    const outcome = await processStripeEvent(event);
    if (outcome.stockChanged) revalidateTag(CACHE_TAGS.products, "max");
    return Response.json({ received: true, duplicate: !outcome.processed });
  } catch (error) {
    // Non-2xx makes Stripe retry; the transaction rolled back, so the retry starts clean.
    logger.error("Stripe webhook processing failed", {
      eventId: event.id,
      type: event.type,
      error,
    });
    return new Response("Webhook processing failed", { status: 500 });
  }
}
