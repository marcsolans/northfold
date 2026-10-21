import { beforeEach, describe, expect, it } from "vitest";

import { actAs, signInAs } from "../../../../tests/auth";
import { prisma, resetDatabase } from "../../../../tests/db";
import { createProduct } from "../../../../tests/factories";
import {
  getAdminOrder,
  getAdminProduct,
  getDashboardStats,
  listAdminOrders,
  listAdminProducts,
  listCustomers,
} from "@/server/queries/admin";

import * as orderActions from "./orders";
import * as productActions from "./products";

beforeEach(resetDatabase);

/** Every exported admin Server Action, discovered from the modules so new ones are covered. */
const ADMIN_ACTIONS = Object.entries({ ...orderActions, ...productActions }).map(
  // Called with arbitrary arguments on purpose: an attacker can POST anything to an action.
  ([name, action]) =>
    [
      name,
      (...args: unknown[]): Promise<unknown> => Reflect.apply(action, undefined, args),
    ] as const,
);

async function plausibleArgs() {
  const product = await createProduct();
  const formData = new FormData();
  formData.set(
    "file",
    new File([new Uint8Array([0xff, 0xd8, 0xff, 0xe0])], "a.jpg", { type: "image/jpeg" }),
  );
  return {
    product,
    args: [product.id, { orderId: "order_1", status: "SHIPPED" }, formData, true] as unknown[],
  };
}

describe("admin Server Actions", () => {
  it("covers every exported admin action", () => {
    expect(ADMIN_ACTIONS.map(([name]) => name).sort()).toEqual([
      "createProduct",
      "deleteProduct",
      "discardUploadedImage",
      "resolveOrderReview",
      "setProductArchived",
      "updateOrderStatus",
      "updateProduct",
      "uploadProductImage",
    ]);
  });

  it.each([
    ["an anonymous visitor", null, "You need to sign in."],
    ["a signed-in customer", "USER" as const, "You are not allowed to do that."],
  ])("rejects %s for every action without touching data", async (_who, role, message) => {
    if (role) await signInAs(role);
    else actAs(null);
    const { product, args } = await plausibleArgs();

    for (const [name, action] of ADMIN_ACTIONS) {
      // Try the most likely argument shapes for this action.
      for (const first of args) {
        const result = await action(first, args[1]);
        expect(result, `${name}(${typeof first})`).toEqual({ ok: false, error: message });
      }
    }

    const unchanged = await prisma.product.findUniqueOrThrow({ where: { id: product.id } });
    expect(unchanged.isArchived).toBe(false);
    expect(await prisma.product.count()).toBe(1);
  });
});

describe("admin queries", () => {
  it("throw for customers", async () => {
    await signInAs("USER");
    await expect(getDashboardStats()).rejects.toMatchObject({ reason: "forbidden" });
    await expect(listAdminProducts({ status: "all", page: 1 })).rejects.toMatchObject({
      reason: "forbidden",
    });
    await expect(getAdminProduct("x")).rejects.toMatchObject({ reason: "forbidden" });
    await expect(
      listAdminOrders({ page: 1, status: undefined, payment: undefined, q: undefined }),
    ).rejects.toMatchObject({
      reason: "forbidden",
    });
    await expect(getAdminOrder("x")).rejects.toMatchObject({ reason: "forbidden" });
    await expect(listCustomers({ page: 1 })).rejects.toMatchObject({ reason: "forbidden" });
  });
});
