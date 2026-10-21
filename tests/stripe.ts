import { randomUUID } from "node:crypto";

import Stripe from "stripe";

/** Matches STRIPE_WEBHOOK_SECRET in the Vitest environment. */
export const TEST_WEBHOOK_SECRET = "whsec_northfold_unit_tests";

export function checkoutSessionEvent(
  type: string,
  session: Record<string, unknown>,
  id = `evt_test_${randomUUID().replace(/-/g, "")}`,
) {
  return {
    id,
    object: "event",
    type,
    api_version: "2026-09-30.endive",
    created: Math.floor(Date.now() / 1000),
    livemode: false,
    pending_webhooks: 1,
    request: { id: null, idempotency_key: null },
    data: {
      object: {
        id: `cs_test_${randomUUID().replace(/-/g, "")}`,
        object: "checkout.session",
        currency: "usd",
        payment_status: "paid",
        status: "complete",
        payment_intent: "pi_test_123",
        ...session,
      },
    },
  };
}

/** A webhook request signed exactly like Stripe does, using the SDK's test helper. */
export function signedWebhookRequest(event: unknown, secret = TEST_WEBHOOK_SECRET): Request {
  const payload = JSON.stringify(event);
  const signature = Stripe.webhooks.generateTestHeaderString({ payload, secret });
  return new Request("http://localhost:3000/api/stripe/webhook", {
    method: "POST",
    headers: { "content-type": "application/json", "stripe-signature": signature },
    body: payload,
  });
}
