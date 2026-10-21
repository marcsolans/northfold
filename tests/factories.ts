import { randomUUID } from "node:crypto";

import type {
  Category,
  OrderStatus,
  PaymentMethod,
  PaymentStatus,
  ProductType,
  Role,
  Size,
} from "@/generated/prisma/enums";
import { money, toMoneyString } from "@/lib/money";

import { prisma } from "./db";

let sequence = 0;
const next = () => ++sequence;

export async function createUser(overrides: { email?: string; role?: Role; name?: string } = {}) {
  const n = next();
  return prisma.user.create({
    data: {
      id: randomUUID(),
      name: overrides.name ?? `Test User ${n}`,
      email: overrides.email ?? `user${n}-${randomUUID().slice(0, 8)}@northfold.test`,
      emailVerified: true,
      role: overrides.role ?? "USER",
    },
  });
}

interface VariantSpec {
  size?: Size;
  colorName?: string;
  stock?: number;
}

export async function createProduct(
  overrides: {
    name?: string;
    price?: string;
    category?: Category;
    productType?: ProductType;
    isArchived?: boolean;
    variants?: VariantSpec[];
  } = {},
) {
  const n = next();
  const variants = overrides.variants ?? [{ size: "M", colorName: "Black", stock: 10 }];
  return prisma.product.create({
    data: {
      name: overrides.name ?? `Test Product ${n}`,
      slug: `test-product-${n}-${randomUUID().slice(0, 6)}`,
      description: "A product used in tests.",
      price: overrides.price ?? "25.00",
      category: overrides.category ?? "MEN",
      productType: overrides.productType ?? "TSHIRT",
      isArchived: overrides.isArchived ?? false,
      images: {
        create: [{ url: "https://images.unsplash.com/photo-test", alt: "Test image", position: 0 }],
      },
      variants: {
        create: variants.map((variant, index) => ({
          size: variant.size ?? "M",
          colorName: variant.colorName ?? `Color ${index}`,
          colorHex: "#000000",
          sku: `TEST-${n}-${index}-${randomUUID().slice(0, 6)}`.toUpperCase(),
          stock: variant.stock ?? 10,
        })),
      },
    },
    include: { variants: { orderBy: { sku: "asc" } }, images: true },
  });
}

export const testAddress = {
  fullName: "Ada Lovelace",
  phone: "+1 555 010 2030",
  line1: "12 Analytical Way",
  city: "Portland",
  state: "OR",
  postalCode: "97201",
  country: "US",
} as const;

export async function createAddress(userId: string, isDefault = false) {
  return prisma.address.create({ data: { ...testAddress, userId, isDefault } });
}

/** Inserts an order directly (bypassing checkout) with one line of a $40 item plus $10 shipping. */
export async function createOrder(
  userId: string,
  overrides: {
    status?: OrderStatus;
    paymentMethod?: PaymentMethod;
    paymentStatus?: PaymentStatus;
    needsReview?: boolean;
    shippingFullName?: string;
    variantId?: string;
    quantity?: number;
    createdAt?: Date;
  } = {},
) {
  const quantity = overrides.quantity ?? 1;
  const subtotal = money("40.00").times(quantity);
  const paid = overrides.paymentStatus === "PAID";
  return prisma.order.create({
    data: {
      userId,
      status: overrides.status ?? "PENDING",
      paymentMethod: overrides.paymentMethod ?? "CASH_ON_DELIVERY",
      paymentStatus: overrides.paymentStatus ?? "PENDING",
      needsReview: overrides.needsReview ?? false,
      paidAt: paid ? new Date() : null,
      subtotal: toMoneyString(subtotal),
      shippingFee: "10.00",
      tax: "0.00",
      total: toMoneyString(subtotal.plus(10)),
      shippingFullName: overrides.shippingFullName ?? testAddress.fullName,
      shippingPhone: testAddress.phone,
      shippingLine1: testAddress.line1,
      shippingCity: testAddress.city,
      shippingState: testAddress.state,
      shippingPostalCode: testAddress.postalCode,
      shippingCountry: testAddress.country,
      ...(overrides.createdAt ? { createdAt: overrides.createdAt } : {}),
      items: {
        create: [
          {
            variantId: overrides.variantId ?? null,
            productName: "Test Product",
            productSlug: "test-product",
            imageUrl: "https://images.unsplash.com/photo-test",
            size: "M",
            colorName: "Black",
            sku: "TEST-SKU",
            unitPrice: "40.00",
            quantity,
          },
        ],
      },
    },
  });
}
