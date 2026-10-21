import "server-only";

import Stripe from "stripe";

import { env } from "@/env";

let client: Stripe | null = null;

/**
 * Lazily created Stripe client. The SDK pins its own API version, so none is passed here.
 * Throws when Stripe is not configured; callers check `features.stripe` first.
 */
export function getStripe(): Stripe {
  if (!env.STRIPE_SECRET_KEY) throw new Error("STRIPE_SECRET_KEY is not configured");
  client ??= new Stripe(env.STRIPE_SECRET_KEY, {
    maxNetworkRetries: 2,
    appInfo: { name: "Northfold" },
  });
  return client;
}
