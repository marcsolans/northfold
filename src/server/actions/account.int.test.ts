import { beforeEach, describe, expect, it } from "vitest";

import { actAs, signInAs, signUpUser } from "../../../tests/auth";
import { prisma, resetDatabase } from "../../../tests/db";
import { createAddress, createProduct, testAddress } from "../../../tests/factories";

import {
  cancelOrder,
  createAddress as createAddressAction,
  deleteAddress,
  setDefaultAddress,
  updateAddress,
  updateProfile,
} from "./account";
import { placeOrder } from "./checkout";

beforeEach(resetDatabase);

describe("address book", () => {
  it("makes the first address the default and switches the default atomically", async () => {
    const user = await signInAs("USER");
    const first = await createAddressAction({ address: testAddress, isDefault: false });
    const second = await createAddressAction({
      address: { ...testAddress, city: "Seattle" },
      isDefault: true,
    });
    if (!first.ok || !second.ok) throw new Error("create failed");

    const defaults = await prisma.address.findMany({ where: { userId: user.id, isDefault: true } });
    expect(defaults.map((a) => a.id)).toEqual([second.data.id]);

    await setDefaultAddress(first.data.id);
    const after = await prisma.address.findMany({ where: { userId: user.id, isDefault: true } });
    expect(after.map((a) => a.id)).toEqual([first.data.id]);
  });

  it("validates input on the server", async () => {
    await signInAs("USER");
    const result = await createAddressAction({
      address: { ...testAddress, country: "XX" },
      isDefault: false,
    });
    expect(result).toMatchObject({
      ok: false,
      fieldErrors: { "address.country": expect.any(Array) },
    });
  });

  it("never lets a customer touch another customer's address", async () => {
    const owner = await signUpUser();
    const address = await createAddress(owner.user.id, true);
    const intruder = await signUpUser();
    actAs(intruder);

    expect(
      await updateAddress(address.id, {
        address: { ...testAddress, city: "Hacked" },
        isDefault: true,
      }),
    ).toMatchObject({ ok: false });
    expect(await setDefaultAddress(address.id)).toMatchObject({ ok: false });
    expect(await deleteAddress(address.id)).toMatchObject({ ok: false });
    const unchanged = await prisma.address.findUniqueOrThrow({ where: { id: address.id } });
    expect(unchanged.city).toBe("Portland");
  });

  it("promotes another address when the default is deleted", async () => {
    const user = await signInAs("USER");
    const keep = await createAddress(user.id, false);
    const remove = await createAddress(user.id, true);
    await deleteAddress(remove.id);
    expect((await prisma.address.findUniqueOrThrow({ where: { id: keep.id } })).isDefault).toBe(
      true,
    );
  });

  it("updates an own address", async () => {
    const user = await signInAs("USER");
    const address = await createAddress(user.id, true);
    const result = await updateAddress(address.id, {
      address: { ...testAddress, city: "Boise" },
      isDefault: true,
    });
    expect(result.ok).toBe(true);
    expect((await prisma.address.findUniqueOrThrow({ where: { id: address.id } })).city).toBe(
      "Boise",
    );
  });
});

describe("cancelOrder", () => {
  async function placeCod(variantId: string, quantity: number) {
    const result = await placeOrder({
      items: [{ variantId, quantity }],
      shipping: { type: "new", address: testAddress },
      paymentMethod: "CASH_ON_DELIVERY",
    });
    if (!result.ok) throw new Error(result.error);
    return result.data.orderId;
  }

  it("cancels a pending COD order and restocks it in the same transaction", async () => {
    await signInAs("USER");
    const product = await createProduct({ variants: [{ stock: 5 }] });
    const variantId = product.variants[0]!.id;
    const orderId = await placeCod(variantId, 3);
    expect(
      (await prisma.productVariant.findUniqueOrThrow({ where: { id: variantId } })).stock,
    ).toBe(2);

    expect(await cancelOrder({ orderId })).toEqual({ ok: true, data: undefined });
    const order = await prisma.order.findUniqueOrThrow({ where: { id: orderId } });
    expect(order).toMatchObject({ status: "CANCELLED", stockDeducted: false });
    expect(
      (await prisma.productVariant.findUniqueOrThrow({ where: { id: variantId } })).stock,
    ).toBe(5);

    // A second cancel does not restock again.
    expect((await cancelOrder({ orderId })).ok).toBe(false);
    expect(
      (await prisma.productVariant.findUniqueOrThrow({ where: { id: variantId } })).stock,
    ).toBe(5);
  });

  it("refuses orders that are already being processed", async () => {
    await signInAs("USER");
    const product = await createProduct();
    const orderId = await placeCod(product.variants[0]!.id, 1);
    await prisma.order.update({ where: { id: orderId }, data: { status: "PROCESSING" } });
    expect(await cancelOrder({ orderId })).toMatchObject({
      ok: false,
      error: "This order can no longer be cancelled.",
    });
  });

  it("refuses another customer's order", async () => {
    const owner = await signUpUser();
    actAs(owner);
    const product = await createProduct();
    const orderId = await placeCod(product.variants[0]!.id, 1);
    actAs(await signUpUser());
    expect(await cancelOrder({ orderId })).toMatchObject({ ok: false, error: "Order not found." });
    expect((await prisma.order.findUniqueOrThrow({ where: { id: orderId } })).status).toBe(
      "PENDING",
    );
  });
});

describe("updateProfile", () => {
  it("updates the name and rejects empty names", async () => {
    const user = await signInAs("USER");
    expect((await updateProfile({ name: "  Ada King  " })).ok).toBe(true);
    expect((await prisma.user.findUniqueOrThrow({ where: { id: user.id } })).name).toBe("Ada King");
    expect((await updateProfile({ name: "   " })).ok).toBe(false);
  });

  it("requires a session", async () => {
    actAs(null);
    expect(await updateProfile({ name: "Nobody" })).toMatchObject({ ok: false });
  });
});
