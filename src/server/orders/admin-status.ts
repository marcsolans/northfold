import "server-only";

import Stripe from "stripe";

import type { OrderStatus, PaymentStatus } from "@/generated/prisma/enums";
import { logger } from "@/lib/logger";
import { canTransition } from "@/lib/order-status";
import { prisma } from "@/lib/prisma";
import { getStripe } from "@/lib/stripe";

import { UserFacingError } from "../action";

import { decrementStock, outOfStockMessage, restockItems } from "./stock";

const LABEL: Record<OrderStatus, string> = {
  PENDING: "pending",
  PROCESSING: "processing",
  SHIPPED: "shipped",
  DELIVERED: "delivered",
  CANCELLED: "cancelled",
};

export interface StatusChangeResult {
  stockChanged: boolean;
}

async function loadOrder(orderId: string) {
  const order = await prisma.order.findUnique({
    where: { id: orderId },
    include: {
      items: {
        select: { variantId: true, quantity: true, productName: true, size: true, colorName: true },
      },
    },
  });
  if (!order) throw new UserFacingError("Order not found.");
  return order;
}

type LoadedOrder = Awaited<ReturnType<typeof loadOrder>>;

const CONFLICT = "This order was updated by someone else. Refresh the page and try again.";

async function refundStripePayment(order: LoadedOrder): Promise<void> {
  if (!order.stripePaymentIntentId) {
    throw new UserFacingError(
      "This payment has no Stripe payment intent; refund it from the Stripe dashboard.",
    );
  }
  try {
    await getStripe().refunds.create(
      { payment_intent: order.stripePaymentIntentId, metadata: { orderId: order.id } },
      { idempotencyKey: `refund:${order.id}` },
    );
  } catch (error) {
    logger.error("Stripe refund failed", {
      orderId: order.id,
      stripeError:
        error instanceof Stripe.errors.StripeError
          ? { type: error.type, code: error.code }
          : undefined,
      error,
    });
    throw new UserFacingError(
      "Stripe could not refund this payment, so the order was not cancelled.",
    );
  }
}

/** Best effort: an open Checkout Session for a cancelled order should not be payable any more. */
async function expireCheckoutSession(order: LoadedOrder): Promise<void> {
  if (!order.stripeSessionId) return;
  try {
    await getStripe().checkout.sessions.expire(order.stripeSessionId);
  } catch (error) {
    logger.warn("Could not expire Stripe Checkout Session (it may already be closed)", {
      orderId: order.id,
      error,
    });
  }
}

async function startProcessing(order: LoadedOrder): Promise<StatusChangeResult> {
  if (order.paymentMethod === "STRIPE" && order.paymentStatus !== "PAID") {
    throw new UserFacingError("This card order has not been paid yet.");
  }
  let stockChanged = false;
  await prisma.$transaction(async (tx) => {
    if (!order.stockDeducted) {
      // e.g. a paid order that was oversold: take the stock now that it has been replenished.
      const lines = order.items.flatMap((item) =>
        item.variantId
          ? [
              {
                variantId: item.variantId,
                quantity: item.quantity,
                label: `${item.productName} (${item.size} / ${item.colorName})`,
              },
            ]
          : [],
      );
      const { failed } = await decrementStock(tx, lines);
      if (failed.length > 0 || lines.length !== order.items.length) {
        throw new UserFacingError(
          failed.length > 0
            ? outOfStockMessage(failed, "Restock it before processing this order.")
            : "An item of this order no longer exists.",
        );
      }
      stockChanged = true;
    }
    const { count } = await tx.order.updateMany({
      where: { id: order.id, status: order.status },
      data: { status: "PROCESSING", stockDeducted: true },
    });
    if (count === 0) throw new UserFacingError(CONFLICT);
  });
  return { stockChanged };
}

async function cancel(order: LoadedOrder): Promise<StatusChangeResult> {
  let paymentStatus: PaymentStatus = order.paymentStatus;
  if (order.paymentMethod === "STRIPE" && order.paymentStatus === "PAID") {
    await refundStripePayment(order);
    paymentStatus = "REFUNDED";
  } else if (order.paymentMethod === "STRIPE" && order.paymentStatus === "PENDING") {
    await expireCheckoutSession(order);
    paymentStatus = "FAILED";
  }

  await prisma.$transaction(async (tx) => {
    const { count } = await tx.order.updateMany({
      where: { id: order.id, status: order.status },
      data: { status: "CANCELLED", cancelledAt: new Date(), stockDeducted: false, paymentStatus },
    });
    if (count === 0) throw new UserFacingError(CONFLICT);
    if (order.stockDeducted) await restockItems(tx, order.items);
  });
  return { stockChanged: order.stockDeducted };
}

/**
 * Moves an order to a new status. The transition itself must be allowed by the state machine
 * (src/lib/order-status.ts); the business rules for each step live here.
 */
export async function changeOrderStatus(
  orderId: string,
  to: OrderStatus,
): Promise<StatusChangeResult> {
  const order = await loadOrder(orderId);
  if (!canTransition(order.status, to)) {
    throw new UserFacingError(`An order can't go from ${LABEL[order.status]} to ${LABEL[to]}.`);
  }

  const now = new Date();
  const conditional = async (data: Parameters<typeof prisma.order.updateMany>[0]["data"]) => {
    const { count } = await prisma.order.updateMany({
      where: { id: order.id, status: order.status },
      data,
    });
    if (count === 0) throw new UserFacingError(CONFLICT);
    return { stockChanged: false };
  };

  switch (to) {
    case "PROCESSING":
      return startProcessing(order);
    case "SHIPPED":
      return conditional({ status: "SHIPPED", shippedAt: now });
    case "DELIVERED":
      // Cash on delivery is collected at the door.
      return conditional({
        status: "DELIVERED",
        deliveredAt: now,
        ...(order.paymentMethod === "CASH_ON_DELIVERY"
          ? { paymentStatus: "PAID" as const, paidAt: now }
          : {}),
      });
    case "CANCELLED":
      return cancel(order);
    case "PENDING":
      throw new UserFacingError("Orders cannot move back to pending.");
  }
}

export async function resolveReview(orderId: string): Promise<void> {
  const { count } = await prisma.order.updateMany({
    where: { id: orderId, needsReview: true },
    data: { needsReview: false, reviewReason: null },
  });
  if (count === 0) throw new UserFacingError("This order is not flagged for review.");
}
