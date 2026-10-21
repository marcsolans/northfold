import type Stripe from "stripe";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { signInAs } from "../../../tests/auth";
import { prisma, resetDatabase } from "../../../tests/db";
import { createProduct, testAddress } from "../../../tests/factories";

import { placeOrder } from "../actions/checkout";

const createSession =
  vi.fn<
    (
      params: Stripe.Checkout.SessionCreateParams,
      options?: Stripe.RequestOptions,
    ) => Promise<{ id: string; url: string | null }>
  >();

vi.mock("@/lib/stripe", () => ({
  getStripe: () => ({ checkout: { sessions: { create: createSession } } }),
}));

beforeEach(async () => {
  await resetDatabase();
  createSession.mockReset();
});

const cardOrder = (variantId: string, quantity = 1) => ({
  items: [{ variantId, quantity }],
  shipping: { type: "new", address: testAddress },
  paymentMethod: "STRIPE",
});

describe("placeOrder — Stripe", () => {
  it("creates a PENDING order and a Checkout Session priced in integer cents", async () => {
    const user = await signInAs("USER");
    const product = await createProduct({
      name: "Wool Coat",
      price: "45.99",
      variants: [{ stock: 4 }],
    });
    const variant = product.variants[0]!;
    createSession.mockResolvedValue({
      id: "cs_test_abc",
      url: "https://checkout.stripe.com/c/pay/cs_test_abc",
    });

    const before = Math.floor(Date.now() / 1000);
    const result = await placeOrder(cardOrder(variant.id, 2));
    if (!result.ok) throw new Error(result.error);
    expect(result.data.redirectUrl).toBe("https://checkout.stripe.com/c/pay/cs_test_abc");

    const order = await prisma.order.findUniqueOrThrow({ where: { id: result.data.orderId } });
    expect(order).toMatchObject({
      userId: user.id,
      status: "PENDING",
      paymentStatus: "PENDING",
      paymentMethod: "STRIPE",
      stripeSessionId: "cs_test_abc",
      stockDeducted: false,
    });
    // Stock is only taken when the payment is confirmed.
    expect(
      (await prisma.productVariant.findUniqueOrThrow({ where: { id: variant.id } })).stock,
    ).toBe(4);

    const [params, options] = createSession.mock.calls[0]!;
    expect(options).toEqual({ idempotencyKey: `checkout-session:${order.id}` });
    expect(params).toMatchObject({
      mode: "payment",
      client_reference_id: order.id,
      metadata: { orderId: order.id },
      customer_email: user.email,
    });
    expect(params.line_items?.[0]).toMatchObject({
      quantity: 2,
      price_data: { currency: "usd", unit_amount: 4599 },
    });
    // 2 × 45.99 = 91.98 → below the free-shipping threshold.
    expect(params.shipping_options?.[0]?.shipping_rate_data?.fixed_amount?.amount).toBe(1000);
    expect(params.success_url).toContain(`order=${order.id}`);
    expect(params.success_url).toContain("{CHECKOUT_SESSION_ID}");
    const expiresIn = (params.expires_at ?? 0) - before;
    expect(expiresIn).toBeGreaterThanOrEqual(30 * 60);
    expect(expiresIn).toBeLessThanOrEqual(32 * 60);
  });

  it("cancels the order and returns a safe error when Stripe fails", async () => {
    await signInAs("USER");
    const product = await createProduct();
    createSession.mockRejectedValue(new Error("connect ECONNREFUSED api.stripe.com"));

    const result = await placeOrder(cardOrder(product.variants[0]!.id));
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error).not.toContain("ECONNREFUSED");
    const order = await prisma.order.findFirstOrThrow();
    expect(order).toMatchObject({ status: "CANCELLED", paymentStatus: "FAILED" });
  });

  it("refuses to start a payment for items that are out of stock", async () => {
    await signInAs("USER");
    const product = await createProduct({ variants: [{ stock: 1 }] });
    const result = await placeOrder(cardOrder(product.variants[0]!.id, 2));
    expect(result.ok).toBe(false);
    expect(createSession).not.toHaveBeenCalled();
    expect(await prisma.order.count()).toBe(0);
  });
});
