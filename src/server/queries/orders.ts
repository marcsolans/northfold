import "server-only";

import type { Prisma } from "@/generated/prisma/client";
import type { OrderStatus, PaymentMethod, PaymentStatus, Size } from "@/generated/prisma/enums";
import { type MoneyString, toMoneyString } from "@/lib/money";
import { prisma } from "@/lib/prisma";

export interface OrderItemDTO {
  id: string;
  productName: string;
  productSlug: string;
  imageUrl: string | null;
  size: Size;
  colorName: string;
  sku: string;
  unitPrice: MoneyString;
  quantity: number;
  lineTotal: MoneyString;
}

export interface OrderDetailDTO {
  id: string;
  status: OrderStatus;
  paymentMethod: PaymentMethod;
  paymentStatus: PaymentStatus;
  needsReview: boolean;
  reviewReason: string | null;
  subtotal: MoneyString;
  shippingFee: MoneyString;
  tax: MoneyString;
  total: MoneyString;
  shippingAddress: {
    fullName: string;
    phone: string;
    line1: string;
    line2: string | null;
    city: string;
    state: string;
    postalCode: string;
    country: string;
  };
  createdAt: string;
  paidAt: string | null;
  shippedAt: string | null;
  deliveredAt: string | null;
  cancelledAt: string | null;
  items: OrderItemDTO[];
}

export const orderDetailInclude = {
  items: { orderBy: { createdAt: "asc" } },
} satisfies Prisma.OrderInclude;

type OrderRow = Prisma.OrderGetPayload<{ include: typeof orderDetailInclude }>;

export function toOrderDetail(order: OrderRow): OrderDetailDTO {
  return {
    id: order.id,
    status: order.status,
    paymentMethod: order.paymentMethod,
    paymentStatus: order.paymentStatus,
    needsReview: order.needsReview,
    reviewReason: order.reviewReason,
    subtotal: toMoneyString(order.subtotal),
    shippingFee: toMoneyString(order.shippingFee),
    tax: toMoneyString(order.tax),
    total: toMoneyString(order.total),
    shippingAddress: {
      fullName: order.shippingFullName,
      phone: order.shippingPhone,
      line1: order.shippingLine1,
      line2: order.shippingLine2,
      city: order.shippingCity,
      state: order.shippingState,
      postalCode: order.shippingPostalCode,
      country: order.shippingCountry,
    },
    createdAt: order.createdAt.toISOString(),
    paidAt: order.paidAt?.toISOString() ?? null,
    shippedAt: order.shippedAt?.toISOString() ?? null,
    deliveredAt: order.deliveredAt?.toISOString() ?? null,
    cancelledAt: order.cancelledAt?.toISOString() ?? null,
    items: order.items.map((item) => ({
      id: item.id,
      productName: item.productName,
      productSlug: item.productSlug,
      imageUrl: item.imageUrl,
      size: item.size,
      colorName: item.colorName,
      sku: item.sku,
      unitPrice: toMoneyString(item.unitPrice),
      quantity: item.quantity,
      lineTotal: toMoneyString(item.unitPrice.times(item.quantity)),
    })),
  };
}

/** An order of this customer, or null (also for other customers' orders). */
export async function getOrderForUser(
  userId: string,
  orderId: string,
): Promise<OrderDetailDTO | null> {
  const order = await prisma.order.findFirst({
    where: { id: orderId, userId },
    include: orderDetailInclude,
  });
  return order ? toOrderDetail(order) : null;
}

export interface OrderListItemDTO {
  id: string;
  createdAt: string;
  status: OrderStatus;
  paymentStatus: PaymentStatus;
  paymentMethod: PaymentMethod;
  total: MoneyString;
  itemCount: number;
  thumbnails: string[];
}

export interface OrderListPage {
  orders: OrderListItemDTO[];
  total: number;
  page: number;
  totalPages: number;
}

export const ACCOUNT_ORDERS_PAGE_SIZE = 10;

/** The customer's orders, newest first. */
export async function listOrdersForUser(
  userId: string,
  page: number,
  pageSize = ACCOUNT_ORDERS_PAGE_SIZE,
): Promise<OrderListPage> {
  const where = { userId };
  const total = await prisma.order.count({ where });
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const current = Math.min(Math.max(1, page), totalPages);
  const rows = await prisma.order.findMany({
    where,
    orderBy: { createdAt: "desc" },
    skip: (current - 1) * pageSize,
    take: pageSize,
    include: {
      items: { select: { quantity: true, imageUrl: true }, orderBy: { createdAt: "asc" } },
    },
  });
  return {
    total,
    page: current,
    totalPages,
    orders: rows.map((order) => ({
      id: order.id,
      createdAt: order.createdAt.toISOString(),
      status: order.status,
      paymentStatus: order.paymentStatus,
      paymentMethod: order.paymentMethod,
      total: toMoneyString(order.total),
      itemCount: order.items.reduce((sum, item) => sum + item.quantity, 0),
      thumbnails: order.items.flatMap((item) => (item.imageUrl ? [item.imageUrl] : [])).slice(0, 3),
    })),
  };
}
