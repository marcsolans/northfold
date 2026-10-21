import "server-only";

import Stripe from "stripe";

import { env } from "@/env";
import { logger } from "@/lib/logger";
import { money, toCents } from "@/lib/money";
import { orderNumber } from "@/lib/orders";
import { prisma } from "@/lib/prisma";
import { STORE, STRIPE_CHECKOUT_TTL_MINUTES } from "@/lib/store-config";
import { getStripe } from "@/lib/stripe";

import { UserFacingError } from "../action";

import type { PricedOrder } from "./pricing";

/** Stripe needs at least 30 minutes measured from its own clock; a small buffer avoids rejections. */
const EXPIRY_BUFFER_SECONDS = 60;

export function checkoutSessionParams(input: {
  orderId: string;
  email: string;
  priced: PricedOrder;
  now?: number;
}): Stripe.Checkout.SessionCreateParams {
  const { orderId, email, priced } = input;
  const nowSeconds = Math.floor((input.now ?? Date.now()) / 1000);
  const currency = STORE.currency;

  const lineItems: Stripe.Checkout.SessionCreateParams.LineItem[] = priced.lines.map((line) => ({
    quantity: line.quantity,
    price_data: {
      currency,
      // Integer cents, computed from the server-side Decimal price.
      unit_amount: toCents(line.unitPrice),
      product_data: {
        name: `${line.snapshot.productName} — ${line.snapshot.size} / ${line.snapshot.colorName}`,
        ...(line.snapshot.imageUrl ? { images: [line.snapshot.imageUrl] } : {}),
        metadata: { variantId: line.variantId, sku: line.snapshot.sku },
      },
    },
  }));
  if (money(priced.tax).greaterThan(0)) {
    lineItems.push({
      quantity: 1,
      price_data: {
        currency,
        unit_amount: toCents(priced.tax),
        product_data: { name: "Sales tax" },
      },
    });
  }

  const freeShipping = money(priced.shippingFee).isZero();
  return {
    mode: "payment",
    line_items: lineItems,
    shipping_options: [
      {
        shipping_rate_data: {
          type: "fixed_amount",
          display_name: freeShipping ? "Free standard shipping" : "Standard shipping",
          fixed_amount: { amount: toCents(priced.shippingFee), currency },
          delivery_estimate: {
            minimum: { unit: "business_day", value: 3 },
            maximum: { unit: "business_day", value: 5 },
          },
        },
      },
    ],
    client_reference_id: orderId,
    metadata: { orderId },
    payment_intent_data: {
      metadata: { orderId },
      description: `${STORE.name} order ${orderNumber(orderId)}`,
    },
    customer_email: email,
    success_url: `${env.NEXT_PUBLIC_APP_URL}/checkout/success?order=${orderId}&session_id={CHECKOUT_SESSION_ID}`,
    cancel_url: `${env.NEXT_PUBLIC_APP_URL}/cart?checkout=cancelled`,
    expires_at: nowSeconds + STRIPE_CHECKOUT_TTL_MINUTES * 60 + EXPIRY_BUFFER_SECONDS,
  };
}

/**
 * Creates the Stripe Checkout Session for a PENDING order and stores its id on the order.
 * If Stripe fails, the order is cancelled so it never lingers as an unpayable PENDING order.
 */
export async function startStripeCheckout(input: {
  orderId: string;
  email: string;
  priced: PricedOrder;
}): Promise<string> {
  try {
    const session = await getStripe().checkout.sessions.create(checkoutSessionParams(input), {
      idempotencyKey: `checkout-session:${input.orderId}`,
    });
    if (!session.url) throw new Error("Stripe returned a session without a URL");
    await prisma.order.update({
      where: { id: input.orderId },
      data: { stripeSessionId: session.id },
    });
    return session.url;
  } catch (error) {
    logger.error("Could not create Stripe Checkout Session", {
      orderId: input.orderId,
      stripeError:
        error instanceof Stripe.errors.StripeError
          ? { type: error.type, code: error.code }
          : undefined,
      error,
    });
    await prisma.order.update({
      where: { id: input.orderId },
      data: { status: "CANCELLED", paymentStatus: "FAILED", cancelledAt: new Date() },
    });
    throw new UserFacingError(
      "We couldn’t start the card payment. Please try again, or choose cash on delivery.",
    );
  }
}
