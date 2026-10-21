import "server-only";

import type { Prisma } from "@/generated/prisma/client";
import type {
  Category,
  OrderStatus,
  PaymentMethod,
  PaymentStatus,
  ProductType,
  Role,
  Size,
} from "@/generated/prisma/enums";
import { type MoneyString, toMoneyString } from "@/lib/money";
import { prisma } from "@/lib/prisma";
import { CATALOG } from "@/lib/store-config";
import type { AdminOrderFilters } from "@/lib/validators/order";

import { requireAdmin } from "../auth/session";

import { escapeLike } from "./catalog";
import { orderDetailInclude, type OrderDetailDTO, toOrderDetail } from "./orders";

const ADMIN_PAGE_SIZE = 15;

function pageOf(total: number, requested: number, size = ADMIN_PAGE_SIZE) {
  const totalPages = Math.max(1, Math.ceil(total / size));
  const page = Math.min(Math.max(1, requested), totalPages);
  return { page, totalPages, skip: (page - 1) * size, take: size };
}

// ─── Overview ───────────────────────────────────────────────────────────────

export interface DashboardStats {
  revenue: { today: MoneyString; last30Days: MoneyString; allTime: MoneyString };
  paidOrders: { today: number; last30Days: number; allTime: number };
  ordersByStatus: Record<OrderStatus, number>;
  customers: number;
  needsReview: number;
  lowStock: {
    variantId: string;
    productId: string;
    productName: string;
    size: Size;
    colorName: string;
    sku: string;
    stock: number;
  }[];
  recentOrders: {
    id: string;
    createdAt: string;
    customer: string;
    total: MoneyString;
    status: OrderStatus;
    paymentStatus: PaymentStatus;
    paymentMethod: PaymentMethod;
  }[];
  revenueSeries: { date: string; revenue: number }[];
}

function startOfUtcDay(date: Date): Date {
  return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
}

/** Revenue counts PAID orders by payment date, with UTC day boundaries. */
export async function getDashboardStats(now?: Date): Promise<DashboardStats> {
  // Reading the session first makes this request-time work, so the clock is read per request.
  await requireAdmin();
  const today = startOfUtcDay(now ?? new Date());
  const since30 = new Date(today.getTime() - 29 * 24 * 60 * 60 * 1000);
  const paid = { paymentStatus: "PAID" } as const;

  const [todayAgg, last30Agg, allAgg, byStatus, customers, needsReview, lowStock, recent, series] =
    await Promise.all([
      prisma.order.aggregate({
        where: { ...paid, paidAt: { gte: today } },
        _sum: { total: true },
        _count: true,
      }),
      prisma.order.aggregate({
        where: { ...paid, paidAt: { gte: since30 } },
        _sum: { total: true },
        _count: true,
      }),
      prisma.order.aggregate({ where: paid, _sum: { total: true }, _count: true }),
      prisma.order.groupBy({ by: ["status"], _count: { _all: true } }),
      prisma.user.count({ where: { role: "USER" } }),
      prisma.order.count({ where: { needsReview: true } }),
      prisma.productVariant.findMany({
        where: { stock: { lte: CATALOG.lowStockThreshold }, product: { isArchived: false } },
        include: { product: { select: { id: true, name: true } } },
        orderBy: [{ stock: "asc" }, { sku: "asc" }],
        take: 12,
      }),
      prisma.order.findMany({
        orderBy: { createdAt: "desc" },
        take: 6,
        include: { user: { select: { name: true, email: true } } },
      }),
      prisma.$queryRaw<{ day: Date; revenue: Prisma.Decimal }[]>`
        SELECT d::date AS day, COALESCE(SUM(o.total), 0) AS revenue
        FROM generate_series(${since30}::timestamp, ${today}::timestamp, interval '1 day') AS d
        LEFT JOIN orders o
          ON o.payment_status = 'PAID' AND o.paid_at >= d AND o.paid_at < d + interval '1 day'
        GROUP BY d
        ORDER BY d
      `,
    ]);

  const ordersByStatus: Record<OrderStatus, number> = {
    PENDING: 0,
    PROCESSING: 0,
    SHIPPED: 0,
    DELIVERED: 0,
    CANCELLED: 0,
  };
  for (const row of byStatus) ordersByStatus[row.status] = row._count._all;

  return {
    revenue: {
      today: toMoneyString(todayAgg._sum.total ?? 0),
      last30Days: toMoneyString(last30Agg._sum.total ?? 0),
      allTime: toMoneyString(allAgg._sum.total ?? 0),
    },
    paidOrders: { today: todayAgg._count, last30Days: last30Agg._count, allTime: allAgg._count },
    ordersByStatus,
    customers,
    needsReview,
    lowStock: lowStock.map((variant) => ({
      variantId: variant.id,
      productId: variant.product.id,
      productName: variant.product.name,
      size: variant.size,
      colorName: variant.colorName,
      sku: variant.sku,
      stock: variant.stock,
    })),
    recentOrders: recent.map((order) => ({
      id: order.id,
      createdAt: order.createdAt.toISOString(),
      customer: order.user.name || order.user.email,
      total: toMoneyString(order.total),
      status: order.status,
      paymentStatus: order.paymentStatus,
      paymentMethod: order.paymentMethod,
    })),
    revenueSeries: series.map((row) => ({
      date: row.day.toISOString().slice(0, 10),
      revenue: Number(toMoneyString(row.revenue)),
    })),
  };
}

// ─── Products ───────────────────────────────────────────────────────────────

export type ProductStatusFilter = "active" | "archived" | "all";

export interface AdminProductRow {
  id: string;
  name: string;
  slug: string;
  price: MoneyString;
  category: Category;
  productType: ProductType;
  isFeatured: boolean;
  isBestseller: boolean;
  isArchived: boolean;
  imageUrl: string | null;
  variantCount: number;
  totalStock: number;
  updatedAt: string;
}

export async function listAdminProducts(options: {
  q?: string;
  status: ProductStatusFilter;
  page: number;
}) {
  await requireAdmin();
  const where: Prisma.ProductWhereInput = {};
  if (options.status === "active") where.isArchived = false;
  if (options.status === "archived") where.isArchived = true;
  if (options.q) {
    const term = escapeLike(options.q);
    where.OR = [
      { name: { contains: term, mode: "insensitive" } },
      { slug: { contains: term, mode: "insensitive" } },
      { variants: { some: { sku: { contains: term, mode: "insensitive" } } } },
    ];
  }
  const total = await prisma.product.count({ where });
  const { page, totalPages, skip, take } = pageOf(total, options.page);
  const rows = await prisma.product.findMany({
    where,
    orderBy: [{ updatedAt: "desc" }, { id: "asc" }],
    skip,
    take,
    include: {
      images: { orderBy: { position: "asc" }, take: 1, select: { url: true } },
      variants: { select: { stock: true } },
    },
  });
  const products: AdminProductRow[] = rows.map((row) => ({
    id: row.id,
    name: row.name,
    slug: row.slug,
    price: toMoneyString(row.price),
    category: row.category,
    productType: row.productType,
    isFeatured: row.isFeatured,
    isBestseller: row.isBestseller,
    isArchived: row.isArchived,
    imageUrl: row.images[0]?.url ?? null,
    variantCount: row.variants.length,
    totalStock: row.variants.reduce((sum, variant) => sum + variant.stock, 0),
    updatedAt: row.updatedAt.toISOString(),
  }));
  return { products, total, page, totalPages };
}

export interface AdminProductDetail {
  id: string;
  name: string;
  slug: string;
  description: string;
  price: MoneyString;
  category: Category;
  productType: ProductType;
  isFeatured: boolean;
  isBestseller: boolean;
  isArchived: boolean;
  images: { url: string; publicId: string | null; alt: string }[];
  variants: {
    id: string;
    size: Size;
    colorName: string;
    colorHex: string;
    sku: string;
    stock: number;
    hasOrders: boolean;
  }[];
  hasOrders: boolean;
}

export async function getAdminProduct(productId: string): Promise<AdminProductDetail | null> {
  await requireAdmin();
  const product = await prisma.product.findUnique({
    where: { id: productId },
    include: {
      images: { orderBy: { position: "asc" } },
      variants: {
        orderBy: [{ colorName: "asc" }, { size: "asc" }],
        include: { _count: { select: { orderItems: true } } },
      },
    },
  });
  if (!product) return null;
  const variants = product.variants.map((variant) => ({
    id: variant.id,
    size: variant.size,
    colorName: variant.colorName,
    colorHex: variant.colorHex,
    sku: variant.sku,
    stock: variant.stock,
    hasOrders: variant._count.orderItems > 0,
  }));
  return {
    id: product.id,
    name: product.name,
    slug: product.slug,
    description: product.description,
    price: toMoneyString(product.price),
    category: product.category,
    productType: product.productType,
    isFeatured: product.isFeatured,
    isBestseller: product.isBestseller,
    isArchived: product.isArchived,
    images: product.images.map((image) => ({
      url: image.url,
      publicId: image.publicId,
      alt: image.alt,
    })),
    variants,
    hasOrders: variants.some((variant) => variant.hasOrders),
  };
}

// ─── Orders ─────────────────────────────────────────────────────────────────

export interface AdminOrderRow {
  id: string;
  createdAt: string;
  customerName: string;
  customerEmail: string;
  total: MoneyString;
  status: OrderStatus;
  paymentStatus: PaymentStatus;
  paymentMethod: PaymentMethod;
  needsReview: boolean;
  itemCount: number;
}

export function buildAdminOrderWhere(
  filters: AdminOrderFilters & { review?: boolean },
): Prisma.OrderWhereInput {
  const where: Prisma.OrderWhereInput = {};
  if (filters.status) where.status = filters.status;
  if (filters.payment) where.paymentMethod = filters.payment;
  if (filters.review) where.needsReview = true;
  if (filters.q) {
    const term = escapeLike(filters.q.trim());
    const idSuffix = term.replace(/^nf-/i, "").toLowerCase();
    where.OR = [
      { id: { endsWith: idSuffix } },
      { user: { email: { contains: term, mode: "insensitive" } } },
      { shippingFullName: { contains: term, mode: "insensitive" } },
    ];
  }
  return where;
}

export async function listAdminOrders(filters: AdminOrderFilters & { review?: boolean }) {
  await requireAdmin();
  const where = buildAdminOrderWhere(filters);
  const total = await prisma.order.count({ where });
  const { page, totalPages, skip, take } = pageOf(total, filters.page);
  const rows = await prisma.order.findMany({
    where,
    orderBy: { createdAt: "desc" },
    skip,
    take,
    include: {
      user: { select: { name: true, email: true } },
      items: { select: { quantity: true } },
    },
  });
  const orders: AdminOrderRow[] = rows.map((order) => ({
    id: order.id,
    createdAt: order.createdAt.toISOString(),
    customerName: order.user.name,
    customerEmail: order.user.email,
    total: toMoneyString(order.total),
    status: order.status,
    paymentStatus: order.paymentStatus,
    paymentMethod: order.paymentMethod,
    needsReview: order.needsReview,
    itemCount: order.items.reduce((sum, item) => sum + item.quantity, 0),
  }));
  return { orders, total, page, totalPages };
}

export interface AdminOrderDetail extends OrderDetailDTO {
  customer: { id: string; name: string; email: string };
  stockDeducted: boolean;
  stripeSessionId: string | null;
  stripePaymentIntentId: string | null;
}

export async function getAdminOrder(orderId: string): Promise<AdminOrderDetail | null> {
  await requireAdmin();
  const order = await prisma.order.findUnique({
    where: { id: orderId },
    include: { ...orderDetailInclude, user: { select: { id: true, name: true, email: true } } },
  });
  if (!order) return null;
  return {
    ...toOrderDetail(order),
    customer: order.user,
    stockDeducted: order.stockDeducted,
    stripeSessionId: order.stripeSessionId,
    stripePaymentIntentId: order.stripePaymentIntentId,
  };
}

// ─── Customers ──────────────────────────────────────────────────────────────

export interface AdminCustomerRow {
  id: string;
  name: string;
  email: string;
  role: Role;
  joinedAt: string;
  orderCount: number;
  totalSpent: MoneyString;
}

/** Everyone with an account, with order count and the total of their paid orders. */
export async function listCustomers(options: { q?: string; page: number }) {
  await requireAdmin();
  const where: Prisma.UserWhereInput = {};
  if (options.q) {
    const term = escapeLike(options.q);
    where.OR = [
      { name: { contains: term, mode: "insensitive" } },
      { email: { contains: term, mode: "insensitive" } },
    ];
  }
  const total = await prisma.user.count({ where });
  const { page, totalPages, skip, take } = pageOf(total, options.page);
  const users = await prisma.user.findMany({
    where,
    orderBy: { createdAt: "desc" },
    skip,
    take,
    select: {
      id: true,
      name: true,
      email: true,
      role: true,
      createdAt: true,
      _count: { select: { orders: true } },
    },
  });
  const spent = await prisma.order.groupBy({
    by: ["userId"],
    where: { userId: { in: users.map((user) => user.id) }, paymentStatus: "PAID" },
    _sum: { total: true },
  });
  const spentBy = new Map(spent.map((row) => [row.userId, row._sum.total]));
  const customers: AdminCustomerRow[] = users.map((user) => ({
    id: user.id,
    name: user.name,
    email: user.email,
    role: user.role,
    joinedAt: user.createdAt.toISOString(),
    orderCount: user._count.orders,
    totalSpent: toMoneyString(spentBy.get(user.id) ?? 0),
  }));
  return { customers, total, page, totalPages };
}
