import "server-only";

import { features } from "@/env";
import type { Prisma } from "@/generated/prisma/client";
import { prisma } from "@/lib/prisma";
import { type AddressData, addressSchema } from "@/lib/validators/address";
import type { PlaceOrderData } from "@/lib/validators/checkout";

import { UserFacingError } from "../action";
import type { SessionUser } from "../auth/session";

import { type PricedOrder, priceOrder } from "./pricing";
import { decrementStock, OutOfStockError, outOfStockMessage } from "./stock";
import { startStripeCheckout } from "./stripe-checkout";

export interface PlaceOrderResult {
  orderId: string;
  /** Where the browser goes next: the confirmation page (COD) or Stripe Checkout. */
  redirectUrl: string;
}

interface ResolvedShipping {
  address: AddressData;
  save: boolean;
}

async function resolveShipping(
  userId: string,
  shipping: PlaceOrderData["shipping"],
): Promise<ResolvedShipping> {
  if (shipping.type === "new") return { address: shipping.address, save: shipping.saveAddress };
  // Ownership check: an address id from another account is treated as not found.
  const saved = await prisma.address.findFirst({ where: { id: shipping.addressId, userId } });
  if (!saved) throw new UserFacingError("Please choose one of your saved addresses.");
  // Re-validated so a stored address that no longer meets the rules cannot be shipped to.
  const address = addressSchema.parse({ ...saved, line2: saved.line2 ?? undefined });
  return { address, save: false };
}

async function saveAddress(tx: Prisma.TransactionClient, userId: string, address: AddressData) {
  const existing = await tx.address.count({ where: { userId } });
  await tx.address.create({
    data: { ...address, line2: address.line2 ?? null, userId, isDefault: existing === 0 },
  });
}

/** Order + items, with price, product and address snapshots (history never joins back). */
export function buildOrderData(
  userId: string,
  paymentMethod: PlaceOrderData["paymentMethod"],
  priced: PricedOrder,
  address: AddressData,
  stockDeducted: boolean,
): Prisma.OrderUncheckedCreateInput {
  return {
    userId,
    paymentMethod,
    status: "PENDING",
    paymentStatus: "PENDING",
    stockDeducted,
    subtotal: priced.subtotal,
    shippingFee: priced.shippingFee,
    tax: priced.tax,
    total: priced.total,
    shippingFullName: address.fullName,
    shippingPhone: address.phone,
    shippingLine1: address.line1,
    shippingLine2: address.line2 ?? null,
    shippingCity: address.city,
    shippingState: address.state,
    shippingPostalCode: address.postalCode,
    shippingCountry: address.country,
    items: {
      create: priced.lines.map((line) => ({
        variantId: line.variantId,
        productName: line.snapshot.productName,
        productSlug: line.snapshot.productSlug,
        imageUrl: line.snapshot.imageUrl,
        size: line.snapshot.size,
        colorName: line.snapshot.colorName,
        sku: line.snapshot.sku,
        unitPrice: line.unitPrice,
        quantity: line.quantity,
      })),
    },
  };
}

function assertInStock(priced: PricedOrder): void {
  const short = priced.lines.filter((line) => line.stock < line.quantity).map((line) => line.label);
  if (short.length > 0) throw new UserFacingError(outOfStockMessage(short));
}

/**
 * Cash on delivery: one transaction creates the order and takes the stock. Each decrement is
 * conditional (`stock >= quantity`); if any line cannot be taken, everything rolls back.
 */
async function placeCashOnDeliveryOrder(
  user: SessionUser,
  priced: PricedOrder,
  shipping: ResolvedShipping,
): Promise<PlaceOrderResult> {
  try {
    const order = await prisma.$transaction(async (tx) => {
      const { failed } = await decrementStock(tx, priced.lines);
      if (failed.length > 0) throw new OutOfStockError(failed);
      if (shipping.save) await saveAddress(tx, user.id, shipping.address);
      return tx.order.create({
        data: buildOrderData(user.id, "CASH_ON_DELIVERY", priced, shipping.address, true),
        select: { id: true },
      });
    });
    return { orderId: order.id, redirectUrl: `/checkout/success?order=${order.id}` };
  } catch (error) {
    if (error instanceof OutOfStockError)
      throw new UserFacingError(outOfStockMessage(error.labels));
    throw error;
  }
}

/**
 * Card payment: stock is checked now but only taken when Stripe confirms the payment (webhook),
 * so abandoned checkouts never hold inventory.
 */
async function placeStripeOrder(
  user: SessionUser,
  priced: PricedOrder,
  shipping: ResolvedShipping,
): Promise<PlaceOrderResult> {
  if (!features.stripe) {
    throw new UserFacingError(
      "Card payments are not available right now. Please choose cash on delivery.",
    );
  }
  const order = await prisma.$transaction(async (tx) => {
    if (shipping.save) await saveAddress(tx, user.id, shipping.address);
    return tx.order.create({
      data: buildOrderData(user.id, "STRIPE", priced, shipping.address, false),
      select: { id: true },
    });
  });
  const checkoutUrl = await startStripeCheckout({ orderId: order.id, email: user.email, priced });
  return { orderId: order.id, redirectUrl: checkoutUrl };
}

export async function placeOrderForUser(
  user: SessionUser,
  input: PlaceOrderData,
): Promise<PlaceOrderResult> {
  const priced = await priceOrder(input.items);
  assertInStock(priced);
  const shipping = await resolveShipping(user.id, input.shipping);
  return input.paymentMethod === "CASH_ON_DELIVERY"
    ? placeCashOnDeliveryOrder(user, priced, shipping)
    : placeStripeOrder(user, priced, shipping);
}
