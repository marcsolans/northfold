import { beforeEach, describe, expect, it } from "vitest";

import { signUpUser } from "../../../tests/auth";
import { prisma, resetDatabase } from "../../../tests/db";
import { createProduct, testAddress } from "../../../tests/factories";
import { checkoutSessionEvent, signedWebhookRequest } from "../../../tests/stripe";
import { POST } from "@/app/api/stripe/webhook/route";
import { toCents } from "@/lib/money";

import { buildOrderData } from "../orders/place-order";
import { priceOrder } from "../orders/pricing";

beforeEach(resetDatabase);

/** A PENDING Stripe order exactly as placeOrder leaves it before payment. */
async function pendingStripeOrder(options: { stock?: number; quantity?: number } = {}) {
  const { user } = await signUpUser();
  const product = await createProduct({
    price: "60.00",
    variants: [{ stock: options.stock ?? 5 }],
  });
  const variant = product.variants[0]!;
  const priced = await priceOrder([{ variantId: variant.id, quantity: options.quantity ?? 2 }]);
  const order = await prisma.order.create({
    data: {
      ...buildOrderData(user.id, "STRIPE", priced, { ...testAddress, line2: undefined }, false),
      stripeSessionId: "cs_test_pending",
    },
  });
  return { order, variant };
}

const completed = (orderId: string, amount: number, extra: Record<string, unknown> = {}) =>
  checkoutSessionEvent("checkout.session.completed", {
    id: "cs_test_pending",
    client_reference_id: orderId,
    metadata: { orderId },
    amount_total: amount,
    ...extra,
  });

async function stockOf(variantId: string) {
  return (await prisma.productVariant.findUniqueOrThrow({ where: { id: variantId } })).stock;
}

describe("POST /api/stripe/webhook", () => {
  it("rejects a missing or invalid signature with 400", async () => {
    const { order } = await pendingStripeOrder();
    const event = completed(order.id, toCents(order.total));

    const unsigned = new Request("http://localhost:3000/api/stripe/webhook", {
      method: "POST",
      body: JSON.stringify(event),
    });
    expect((await POST(unsigned)).status).toBe(400);

    const forged = signedWebhookRequest(event, "whsec_wrong_secret");
    expect((await POST(forged)).status).toBe(400);

    const tampered = signedWebhookRequest(event);
    const body = (await tampered.text()).replace('"paid"', '"unpaid"');
    const replay = new Request(tampered.url, { method: "POST", headers: tampered.headers, body });
    expect((await POST(replay)).status).toBe(400);

    expect((await prisma.order.findUniqueOrThrow({ where: { id: order.id } })).paymentStatus).toBe(
      "PENDING",
    );
    expect(await prisma.stripeEvent.count()).toBe(0);
  });

  it("marks the order paid and takes the stock on checkout.session.completed", async () => {
    const { order, variant } = await pendingStripeOrder({ stock: 5, quantity: 2 });
    const response = await POST(signedWebhookRequest(completed(order.id, toCents(order.total))));
    expect(response.status).toBe(200);

    const updated = await prisma.order.findUniqueOrThrow({ where: { id: order.id } });
    expect(updated).toMatchObject({
      status: "PROCESSING",
      paymentStatus: "PAID",
      stockDeducted: true,
      needsReview: false,
      stripePaymentIntentId: "pi_test_123",
    });
    expect(updated.paidAt).not.toBeNull();
    expect(await stockOf(variant.id)).toBe(3);
  });

  it("processes the same event only once, even when re-sent", async () => {
    const { order, variant } = await pendingStripeOrder({ stock: 5, quantity: 2 });
    const event = completed(order.id, toCents(order.total));

    const first = await POST(signedWebhookRequest(event));
    const second = await POST(signedWebhookRequest(event));
    expect(first.status).toBe(200);
    expect(second.status).toBe(200);
    expect(await second.json()).toEqual({ received: true, duplicate: true });
    expect(await stockOf(variant.id)).toBe(3);
    expect(await prisma.stripeEvent.count()).toBe(1);
  });

  it("processes concurrent duplicate deliveries exactly once", async () => {
    const { order, variant } = await pendingStripeOrder({ stock: 5, quantity: 2 });
    const event = completed(order.id, toCents(order.total));
    const responses = await Promise.all([
      POST(signedWebhookRequest(event)),
      POST(signedWebhookRequest(event)),
      POST(signedWebhookRequest(event)),
    ]);
    expect(responses.map((r) => r.status)).toEqual([200, 200, 200]);
    expect(await stockOf(variant.id)).toBe(3);
  });

  it("does not double-process a different event for an already paid order", async () => {
    const { order, variant } = await pendingStripeOrder({ stock: 5, quantity: 1 });
    await POST(signedWebhookRequest(completed(order.id, toCents(order.total))));
    await POST(
      signedWebhookRequest(
        checkoutSessionEvent("checkout.session.async_payment_succeeded", {
          id: "cs_test_pending",
          client_reference_id: order.id,
          amount_total: toCents(order.total),
        }),
      ),
    );
    expect(await stockOf(variant.id)).toBe(4);
  });

  it("flags an oversold order for review and leaves stock untouched", async () => {
    const { order, variant } = await pendingStripeOrder({ stock: 5, quantity: 2 });
    await prisma.productVariant.update({ where: { id: variant.id }, data: { stock: 1 } });

    expect(
      (await POST(signedWebhookRequest(completed(order.id, toCents(order.total))))).status,
    ).toBe(200);
    const updated = await prisma.order.findUniqueOrThrow({ where: { id: order.id } });
    expect(updated).toMatchObject({
      paymentStatus: "PAID",
      status: "PENDING",
      stockDeducted: false,
      needsReview: true,
    });
    expect(updated.reviewReason).toContain("out of stock");
    expect(await stockOf(variant.id)).toBe(1);
  });

  it("flags an amount mismatch", async () => {
    const { order } = await pendingStripeOrder();
    await POST(signedWebhookRequest(completed(order.id, 1)));
    const updated = await prisma.order.findUniqueOrThrow({ where: { id: order.id } });
    expect(updated.paymentStatus).toBe("PAID");
    expect(updated.needsReview).toBe(true);
  });

  it("waits for confirmation when a delayed payment method completes unpaid", async () => {
    const { order, variant } = await pendingStripeOrder();
    await POST(
      signedWebhookRequest(completed(order.id, toCents(order.total), { payment_status: "unpaid" })),
    );
    expect((await prisma.order.findUniqueOrThrow({ where: { id: order.id } })).paymentStatus).toBe(
      "PENDING",
    );
    expect(await stockOf(variant.id)).toBe(5);
  });

  it("cancels the order when the session expires", async () => {
    const { order, variant } = await pendingStripeOrder();
    const expired = checkoutSessionEvent("checkout.session.expired", {
      id: "cs_test_pending",
      client_reference_id: order.id,
      payment_status: "unpaid",
      status: "expired",
    });
    expect((await POST(signedWebhookRequest(expired))).status).toBe(200);
    const updated = await prisma.order.findUniqueOrThrow({ where: { id: order.id } });
    expect(updated).toMatchObject({ status: "CANCELLED", paymentStatus: "FAILED" });
    expect(updated.cancelledAt).not.toBeNull();
    expect(await stockOf(variant.id)).toBe(5);
  });

  it("flags a payment that arrives after the order was cancelled", async () => {
    const { order } = await pendingStripeOrder();
    await prisma.order.update({
      where: { id: order.id },
      data: { status: "CANCELLED", paymentStatus: "FAILED" },
    });
    await POST(signedWebhookRequest(completed(order.id, toCents(order.total))));
    const updated = await prisma.order.findUniqueOrThrow({ where: { id: order.id } });
    expect(updated).toMatchObject({
      paymentStatus: "PAID",
      status: "CANCELLED",
      needsReview: true,
    });
  });

  it("acknowledges events for unknown orders and unrelated event types", async () => {
    const unknown = completed("order-that-does-not-exist", 1000);
    expect((await POST(signedWebhookRequest(unknown))).status).toBe(200);
    const other = {
      ...checkoutSessionEvent("customer.created", {}),
      data: { object: { id: "cus_1" } },
    };
    expect((await POST(signedWebhookRequest(other))).status).toBe(200);
    expect(await prisma.stripeEvent.count()).toBe(2);
  });
});
