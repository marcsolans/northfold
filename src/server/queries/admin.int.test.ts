import { beforeEach, describe, expect, it } from "vitest";

import { signInAs, signUpUser } from "../../../tests/auth";
import { prisma, resetDatabase } from "../../../tests/db";
import { createOrder, createProduct, createUser } from "../../../tests/factories";
import { orderNumber } from "@/lib/orders";
import type { AdminOrderFilters } from "@/lib/validators/order";

import {
  getAdminOrder,
  getAdminProduct,
  listAdminOrders,
  listAdminProducts,
  listCustomers,
} from "./admin";

beforeEach(async () => {
  await resetDatabase();
});

const noFilters: AdminOrderFilters = {
  status: undefined,
  payment: undefined,
  q: undefined,
  page: 1,
};

describe("listAdminProducts", () => {
  it("filters by archive status and searches names and SKUs", async () => {
    await signInAs("ADMIN");
    const shirt = await createProduct({
      name: "Linen Camp Shirt",
      variants: [{ stock: 3 }, { size: "L", stock: 4 }],
    });
    const coat = await createProduct({ name: "Wool Overcoat", isArchived: true });

    const active = await listAdminProducts({ status: "active", page: 1 });
    expect(active.products.map((product) => product.id)).toEqual([shirt.id]);
    expect(active.products[0]).toMatchObject({
      variantCount: 2,
      totalStock: 7,
      price: "25.00",
      imageUrl: "https://images.unsplash.com/photo-test",
    });

    const archived = await listAdminProducts({ status: "archived", page: 1 });
    expect(archived.products.map((product) => product.id)).toEqual([coat.id]);
    expect((await listAdminProducts({ status: "all", page: 1 })).total).toBe(2);

    const byName = await listAdminProducts({ status: "all", q: "LINEN", page: 1 });
    expect(byName.products.map((product) => product.id)).toEqual([shirt.id]);
    const sku = coat.variants[0]!.sku;
    const bySku = await listAdminProducts({ status: "all", q: sku.slice(-6), page: 1 });
    expect(bySku.products.map((product) => product.id)).toEqual([coat.id]);
    expect((await listAdminProducts({ status: "all", q: "%", page: 1 })).total).toBe(0);
  });
});

describe("getAdminProduct", () => {
  it("marks variants that appear in orders", async () => {
    await signInAs("ADMIN");
    const product = await createProduct({ variants: [{ size: "S" }, { size: "M" }] });
    const [ordered, unordered] = product.variants;
    const customer = await createUser();
    await createOrder(customer.id, { variantId: ordered!.id });

    const detail = await getAdminProduct(product.id);
    expect(detail?.hasOrders).toBe(true);
    const flags = new Map(detail?.variants.map((variant) => [variant.id, variant.hasOrders]));
    expect(flags.get(ordered!.id)).toBe(true);
    expect(flags.get(unordered!.id)).toBe(false);
    await expect(getAdminProduct("missing")).resolves.toBeNull();
  });
});

describe("listAdminOrders", () => {
  it("filters by status, payment method, review flag and search", async () => {
    await signInAs("ADMIN");
    const ada = await createUser({ name: "Ada", email: "ada@northfold.test" });
    const grace = await createUser({ name: "Grace", email: "grace@northfold.test" });
    const pendingCod = await createOrder(ada.id, { quantity: 2 });
    const paidCard = await createOrder(grace.id, {
      status: "PROCESSING",
      paymentMethod: "STRIPE",
      paymentStatus: "PAID",
      shippingFullName: "Grace Hopper",
    });
    const flagged = await createOrder(grace.id, {
      paymentMethod: "STRIPE",
      paymentStatus: "PAID",
      needsReview: true,
    });

    const ids = async (filters: Partial<AdminOrderFilters> & { review?: boolean }) =>
      (await listAdminOrders({ ...noFilters, ...filters })).orders.map((order) => order.id).sort();

    expect(await ids({})).toEqual([pendingCod.id, paidCard.id, flagged.id].sort());
    expect(await ids({ status: "PROCESSING" })).toEqual([paidCard.id]);
    expect(await ids({ payment: "CASH_ON_DELIVERY" })).toEqual([pendingCod.id]);
    expect(await ids({ review: true })).toEqual([flagged.id]);
    expect(await ids({ q: "ADA@NORTHFOLD" })).toEqual([pendingCod.id]);
    expect(await ids({ q: "hopper" })).toEqual([paidCard.id]);
    expect(await ids({ q: orderNumber(flagged.id) })).toEqual([flagged.id]);

    const [row] = (await listAdminOrders({ ...noFilters, payment: "CASH_ON_DELIVERY" })).orders;
    expect(row).toMatchObject({ customerName: "Ada", itemCount: 2, total: "90.00" });
  });
});

describe("getAdminOrder", () => {
  it("includes the customer and payment references", async () => {
    await signInAs("ADMIN");
    const customer = await createUser({ name: "Ada" });
    const order = await createOrder(customer.id);
    await prisma.order.update({
      where: { id: order.id },
      data: { stripeSessionId: "cs_test_ref", stripePaymentIntentId: "pi_test_ref" },
    });

    await expect(getAdminOrder(order.id)).resolves.toMatchObject({
      id: order.id,
      customer: { id: customer.id, name: "Ada" },
      stockDeducted: false,
      stripeSessionId: "cs_test_ref",
      stripePaymentIntentId: "pi_test_ref",
    });
    await expect(getAdminOrder("missing")).resolves.toBeNull();
  });
});

describe("listCustomers", () => {
  it("counts every order but only paid ones towards total spent", async () => {
    const admin = await signInAs("ADMIN");
    const { user: shopper } = await signUpUser({ name: "Ada Shopper" });
    await createOrder(shopper.id, { paymentStatus: "PAID", quantity: 2 });
    await createOrder(shopper.id, { paymentStatus: "PAID" });
    await createOrder(shopper.id, { status: "CANCELLED", paymentStatus: "REFUNDED" });
    await createOrder(shopper.id);

    const { customers, total } = await listCustomers({ page: 1 });
    expect(total).toBe(2);
    const row = customers.find((customer) => customer.id === shopper.id);
    expect(row).toMatchObject({ role: "USER", orderCount: 4, totalSpent: "140.00" });
    expect(customers.find((customer) => customer.id === admin.id)).toMatchObject({
      role: "ADMIN",
      orderCount: 0,
      totalSpent: "0.00",
    });

    const search = await listCustomers({ q: "ada shop", page: 1 });
    expect(search.customers.map((customer) => customer.id)).toEqual([shopper.id]);
  });
});
