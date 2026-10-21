import { beforeEach, describe, expect, it } from "vitest";

import { resetDatabase } from "../../../tests/db";
import { createOrder, createUser } from "../../../tests/factories";

import { getOrderForUser, listOrdersForUser } from "./orders";

beforeEach(resetDatabase);

describe("getOrderForUser", () => {
  it("returns the customer's own order with money as exact strings", async () => {
    const user = await createUser();
    const order = await createOrder(user.id, { quantity: 2 });

    await expect(getOrderForUser(user.id, order.id)).resolves.toMatchObject({
      id: order.id,
      subtotal: "80.00",
      shippingFee: "10.00",
      tax: "0.00",
      total: "90.00",
      paidAt: null,
      shippingAddress: { fullName: "Ada Lovelace", country: "US" },
      items: [{ sku: "TEST-SKU", quantity: 2, unitPrice: "40.00", lineTotal: "80.00" }],
    });
  });

  it("hides other customers' orders", async () => {
    const [owner, other] = await Promise.all([createUser(), createUser()]);
    const order = await createOrder(owner.id);
    await expect(getOrderForUser(other.id, order.id)).resolves.toBeNull();
  });
});

describe("listOrdersForUser", () => {
  it("pages the customer's orders newest first and clamps the page number", async () => {
    const [user, other] = await Promise.all([createUser(), createUser()]);
    for (const day of [1, 2, 3]) {
      await createOrder(user.id, { quantity: day, createdAt: new Date(Date.UTC(2026, 0, day)) });
    }
    await createOrder(other.id);

    const first = await listOrdersForUser(user.id, 1, 2);
    expect(first).toMatchObject({ total: 3, page: 1, totalPages: 2 });
    expect(first.orders.map((order) => order.itemCount)).toEqual([3, 2]);
    expect(first.orders[0]).toMatchObject({
      total: "130.00",
      thumbnails: ["https://images.unsplash.com/photo-test"],
    });

    const clamped = await listOrdersForUser(user.id, 99, 2);
    expect(clamped.page).toBe(2);
    expect(clamped.orders.map((order) => order.itemCount)).toEqual([1]);
  });

  it("returns an empty first page for a customer without orders", async () => {
    const user = await createUser();
    await expect(listOrdersForUser(user.id, 3)).resolves.toEqual({
      orders: [],
      total: 0,
      page: 1,
      totalPages: 1,
    });
  });
});
