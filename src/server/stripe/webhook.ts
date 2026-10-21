import "server-only";

import type Stripe from "stripe";

import { Prisma } from "@/generated/prisma/client";
import { logger } from "@/lib/logger";
import { toCents } from "@/lib/money";
import { prisma } from "@/lib/prisma";
import { STORE } from "@/lib/store-config";

import { decrementStock, restockItems } from "../orders/stock";

export interface WebhookOutcome {
  /** False when the event id was already processed (Stripe retries / duplicates). */
  processed: boolean;
  /** True when product stock changed, so catalog caches should be refreshed. */
  stockChanged: boolean;
}

type Tx = Prisma.TransactionClient;

function isUniqueViolation(error: unknown): boolean {
  return error instanceof Prisma.PrismaClientKnownRequestError && error.code === "P2002";
}

function orderIdOf(session: Stripe.Checkout.Session): string | null {
  return session.client_reference_id ?? session.metadata?.orderId ?? null;
}

function paymentIntentIdOf(session: Stripe.Checkout.Session): string | null {
  const intent = session.payment_intent;
  if (!intent) return null;
  return typeof intent === "string" ? intent : intent.id;
}

async function flagForReview(tx: Tx, orderId: string, reason: string): Promise<void> {
  await tx.order.update({
    where: { id: orderId },
    data: { needsReview: true, reviewReason: reason },
  });
}

/**
 * Payment confirmed: mark the order PAID/PROCESSING (only if it is still PENDING) and take the
 * stock conditionally. If stock ran out since checkout, the order stays PAID but PENDING and is
 * flagged for an admin to refund or restock.
 */
async function handlePaid(
  tx: Tx,
  session: Stripe.Checkout.Session,
  eventId: string,
): Promise<boolean> {
  const orderId = orderIdOf(session);
  const context = { eventId, sessionId: session.id, orderId };
  if (!orderId) {
    logger.warn("Stripe session has no order reference; ignored", context);
    return false;
  }
  const order = await tx.order.findUnique({ where: { id: orderId }, include: { items: true } });
  if (!order) {
    logger.warn("Stripe session references an unknown order; ignored", context);
    return false;
  }
  if (order.paymentStatus === "PAID") {
    logger.info("Order already marked paid; nothing to do", context);
    return false;
  }

  const paymentFields = {
    paymentStatus: "PAID" as const,
    paidAt: new Date(),
    stripeSessionId: session.id,
    stripePaymentIntentId: paymentIntentIdOf(session),
  };

  // Paid, but the order is no longer waiting for payment (e.g. cancelled in the meantime).
  const claimed = await tx.order.updateMany({
    where: { id: order.id, status: "PENDING", paymentStatus: "PENDING" },
    data: paymentFields,
  });
  if (claimed.count === 0) {
    await tx.order.update({ where: { id: order.id }, data: paymentFields });
    await flagForReview(
      tx,
      order.id,
      `Payment received while the order was ${order.status.toLowerCase()}.`,
    );
    logger.error("Payment received for an order that was not pending", {
      ...context,
      status: order.status,
    });
    return false;
  }

  const lines = order.items
    .filter((item): item is typeof item & { variantId: string } => item.variantId !== null)
    .map((item) => ({
      variantId: item.variantId,
      quantity: item.quantity,
      label: `${item.productName} (${item.size} / ${item.colorName})`,
    }));
  const missingVariants = order.items.length - lines.length;
  const { failed, taken } = await decrementStock(tx, lines);

  if (failed.length > 0 || missingVariants > 0) {
    // Give back what was taken: the order is either fully stocked or not at all.
    await restockItems(tx, taken);
    const reason = `Paid but out of stock at payment time: ${failed.join(", ") || "a removed variant"}. Refund or restock.`;
    await flagForReview(tx, order.id, reason);
    logger.error("Order oversold after payment — flagged for review", { ...context, failed });
    return false;
  }

  await tx.order.update({
    where: { id: order.id },
    data: { status: "PROCESSING", stockDeducted: true },
  });

  const expected = toCents(order.total);
  if (session.amount_total !== expected || session.currency !== STORE.currency) {
    await flagForReview(
      tx,
      order.id,
      `Stripe charged ${session.amount_total ?? "?"} ${session.currency ?? "?"} but the order total is ${expected} ${STORE.currency}.`,
    );
    logger.error("Stripe amount does not match the order total", {
      ...context,
      amount: session.amount_total,
      expected,
    });
  }
  logger.info("Order paid", context);
  return true;
}

/** Session expired or async payment failed: cancel the order if it is still waiting. */
async function handleUnpaid(
  tx: Tx,
  session: Stripe.Checkout.Session,
  eventId: string,
): Promise<void> {
  const orderId = orderIdOf(session);
  if (!orderId) return;
  const { count } = await tx.order.updateMany({
    where: { id: orderId, status: "PENDING", paymentStatus: "PENDING" },
    data: { status: "CANCELLED", paymentStatus: "FAILED", cancelledAt: new Date() },
  });
  logger.info(
    count > 0 ? "Unpaid order cancelled" : "Unpaid session for a non-pending order; ignored",
    {
      eventId,
      sessionId: session.id,
      orderId,
    },
  );
}

/**
 * Processes a verified Stripe event exactly once. The event id is recorded in the same
 * transaction as its effects: a duplicate delivery hits the primary key and is skipped, and a
 * failure rolls back both, so Stripe's retry processes it again.
 */
export async function processStripeEvent(event: Stripe.Event): Promise<WebhookOutcome> {
  try {
    return await prisma.$transaction(async (tx) => {
      await tx.stripeEvent.create({ data: { id: event.id, type: event.type } });
      let stockChanged = false;

      switch (event.type) {
        case "checkout.session.completed": {
          const session = event.data.object;
          // Delayed payment methods complete as "unpaid" and confirm later.
          if (
            session.payment_status === "paid" ||
            session.payment_status === "no_payment_required"
          ) {
            stockChanged = await handlePaid(tx, session, event.id);
          }
          break;
        }
        case "checkout.session.async_payment_succeeded":
          stockChanged = await handlePaid(tx, event.data.object, event.id);
          break;
        case "checkout.session.async_payment_failed":
        case "checkout.session.expired":
          await handleUnpaid(tx, event.data.object, event.id);
          break;
        default:
          break;
      }
      return { processed: true, stockChanged };
    });
  } catch (error) {
    if (isUniqueViolation(error)) {
      logger.info("Duplicate Stripe event ignored", { eventId: event.id, type: event.type });
      return { processed: false, stockChanged: false };
    }
    throw error;
  }
}
