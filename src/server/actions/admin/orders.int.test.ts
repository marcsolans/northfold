import { randomUUID } from "node:crypto";

import { beforeEach, describe, expect, it, vi } from "vitest";

import { actAs, signInAs, signUpUser } from "../../../../tests/auth";
import { prisma, resetDatabase } from "../../../../tests/db";
import { createProduct, testAddress } from "../../../../tests/factories";
import { getDashboardStats } from "@/server/queries/admin";

import { placeOrder } from "../checkout";

import { resolveOrderReview, updateOrderStatus } from "./orders";

const refundsCreate = vi.fn();
const sessionsExpire = vi.fn();
vi.mock("@/lib/stripe", () => ({
  getStripe: () => ({
    refunds: { create: refundsCreate },
    checkout: { sessions: { expire: sessionsExpire } },
  }),
}));

beforeEach(async () => {
  await resetDatabase();
  refundsCreate.mockReset();
  sessionsExpire.mockReset();
});

async function codOrder(stock = 5, quantity = 2) {
  const product = await createProduct({ price: "50.00", variants: [{ stock }] });
  const variantId = product.variants[0]!.id;
  actAs(await signUpUser());
  const result = await placeOrder({
    items: [{ variantId, quantity }],
    shipping: { type: "new", address: testAddress },
    paymentMethod: "CASH_ON_DELIVERY",
  });
  if (!result.ok) throw new Error(result.error);
  await signInAs("ADMIN");
  return { orderId: result.data.orderId, variantId };
}

async function stripeOrder(paymentStatus: "PAID" | "PENDING", stockDeducted: boolean, stock = 5) {
  const { user } = await signUpUser();
  const product = await createProduct({ price: "50.00", variants: [{ stock }] });
  const variant = product.variants[0]!;
  const sessionId = `cs_test_${randomUUID()}`;
  const order = await prisma.order.create({
    data: {
      userId: user.id,
      paymentMethod: "STRIPE",
      paymentStatus,
      status: "PENDING",
      stockDeducted,
      stripeSessionId: sessionId,
      stripePaymentIntentId: paymentStatus === "PAID" ? "pi_test_x" : null,
      paidAt: paymentStatus === "PAID" ? new Date() : null,
      subtotal: "50.00",
      shippingFee: "10.00",
      tax: "0.00",
      total: "60.00",
      shippingFullName: "A",
      shippingPhone: "+1 555 0100",
      shippingLine1: "1 St",
      shippingCity: "X",
      shippingState: "Y",
      shippingPostalCode: "12345",
      shippingCountry: "US",
      items: {
        create: [
          {
            variantId: variant.id,
            productName: "P",
            productSlug: "p",
            size: "M",
            colorName: "C",
            sku: "S",
            unitPrice: "50.00",
            quantity: 1,
          },
        ],
      },
    },
  });
  await signInAs("ADMIN");
  return { orderId: order.id, variantId: variant.id, sessionId };
}

const stock = async (variantId: string) =>
  (await prisma.productVariant.findUniqueOrThrow({ where: { id: variantId } })).stock;
const orderOf = (orderId: string) => prisma.order.findUniqueOrThrow({ where: { id: orderId } });

describe("updateOrderStatus", () => {
  it("walks a COD order through the happy path and records the cash payment on delivery", async () => {
    const { orderId } = await codOrder();
    for (const status of ["PROCESSING", "SHIPPED", "DELIVERED"] as const) {
      expect(await updateOrderStatus({ orderId, status })).toEqual({ ok: true, data: undefined });
    }
    const order = await orderOf(orderId);
    expect(order).toMatchObject({ status: "DELIVERED", paymentStatus: "PAID" });
    expect(order.shippedAt).not.toBeNull();
    expect(order.deliveredAt).not.toBeNull();
  });

  it.each([
    ["PENDING", "SHIPPED"],
    ["PENDING", "DELIVERED"],
    ["PENDING", "PENDING"],
  ] as const)("rejects the invalid transition %s → %s", async (_from, to) => {
    const { orderId } = await codOrder();
    expect(await updateOrderStatus({ orderId, status: to })).toMatchObject({ ok: false });
    expect((await orderOf(orderId)).status).toBe("PENDING");
  });

  it("rejects transitions out of terminal states", async () => {
    const { orderId } = await codOrder();
    await updateOrderStatus({ orderId, status: "CANCELLED" });
    expect(await updateOrderStatus({ orderId, status: "PROCESSING" })).toMatchObject({ ok: false });
  });

  it("restocks when a COD order is cancelled", async () => {
    const { orderId, variantId } = await codOrder(5, 2);
    expect(await stock(variantId)).toBe(3);
    await updateOrderStatus({ orderId, status: "PROCESSING" });
    expect((await updateOrderStatus({ orderId, status: "CANCELLED" })).ok).toBe(true);
    expect(await stock(variantId)).toBe(5);
    expect(await orderOf(orderId)).toMatchObject({ status: "CANCELLED", stockDeducted: false });
  });

  it("will not process an unpaid card order", async () => {
    const { orderId } = await stripeOrder("PENDING", false);
    expect(await updateOrderStatus({ orderId, status: "PROCESSING" })).toMatchObject({
      ok: false,
      error: "This card order has not been paid yet.",
    });
  });

  it("refunds a paid card order on cancellation", async () => {
    const { orderId, variantId } = await stripeOrder("PAID", true, 4);
    refundsCreate.mockResolvedValue({ id: "re_1" });
    expect((await updateOrderStatus({ orderId, status: "CANCELLED" })).ok).toBe(true);
    expect(refundsCreate).toHaveBeenCalledWith(
      { payment_intent: "pi_test_x", metadata: { orderId } },
      { idempotencyKey: `refund:${orderId}` },
    );
    expect(await orderOf(orderId)).toMatchObject({
      status: "CANCELLED",
      paymentStatus: "REFUNDED",
    });
    expect(await stock(variantId)).toBe(5);
  });

  it("changes nothing when the refund fails", async () => {
    const { orderId } = await stripeOrder("PAID", true);
    refundsCreate.mockRejectedValue(new Error("card_declined"));
    expect(await updateOrderStatus({ orderId, status: "CANCELLED" })).toMatchObject({ ok: false });
    expect(await orderOf(orderId)).toMatchObject({ status: "PENDING", paymentStatus: "PAID" });
  });

  it("expires the checkout session when cancelling an unpaid card order", async () => {
    const { orderId, sessionId } = await stripeOrder("PENDING", false);
    expect((await updateOrderStatus({ orderId, status: "CANCELLED" })).ok).toBe(true);
    expect(sessionsExpire).toHaveBeenCalledWith(sessionId);
    expect(await orderOf(orderId)).toMatchObject({ status: "CANCELLED", paymentStatus: "FAILED" });
  });

  it("takes stock when processing a paid order that was oversold, once restocked", async () => {
    const { orderId, variantId } = await stripeOrder("PAID", false, 0);
    expect(await updateOrderStatus({ orderId, status: "PROCESSING" })).toMatchObject({
      ok: false,
      error: expect.stringContaining("Restock it"),
    });
    await prisma.productVariant.update({ where: { id: variantId }, data: { stock: 3 } });
    expect((await updateOrderStatus({ orderId, status: "PROCESSING" })).ok).toBe(true);
    expect(await stock(variantId)).toBe(2);
    expect(await orderOf(orderId)).toMatchObject({ status: "PROCESSING", stockDeducted: true });
  });

  it("resolves a review flag", async () => {
    const { orderId } = await stripeOrder("PAID", false);
    await prisma.order.update({
      where: { id: orderId },
      data: { needsReview: true, reviewReason: "x" },
    });
    expect((await resolveOrderReview({ orderId })).ok).toBe(true);
    expect(await orderOf(orderId)).toMatchObject({ needsReview: false, reviewReason: null });
    expect((await resolveOrderReview({ orderId })).ok).toBe(false);
  });
});

describe("getDashboardStats", () => {
  it("sums paid revenue by period and counts orders by status", async () => {
    const { orderId } = await codOrder(10, 1); // $50 + $10 shipping, pending (unpaid)
    const paid = await stripeOrder("PAID", true); // $60 paid now
    const old = await stripeOrder("PAID", true);
    await prisma.order.update({
      where: { id: old.orderId },
      data: { paidAt: new Date(Date.now() - 40 * 86_400_000) },
    });

    const stats = await getDashboardStats();
    expect(stats.revenue).toEqual({ today: "60.00", last30Days: "60.00", allTime: "120.00" });
    expect(stats.ordersByStatus.PENDING).toBe(3);
    expect(stats.revenueSeries).toHaveLength(30);
    expect(stats.revenueSeries.at(-1)?.revenue).toBe(60);
    expect(stats.recentOrders.map((o) => o.id)).toEqual(
      expect.arrayContaining([orderId, paid.orderId]),
    );
    expect(stats.customers).toBe(3);
  });
});
