import { beforeEach, describe, expect, it } from "vitest";

import { actAs, signInAs, signUpUser } from "../../../tests/auth";
import { prisma, resetDatabase } from "../../../tests/db";
import { createAddress, createProduct, testAddress } from "../../../tests/factories";
import { RATE_LIMITS } from "@/lib/store-config";

import { placeOrder } from "../actions/checkout";

beforeEach(resetDatabase);

const cod = (
  items: { variantId: string; quantity: number }[],
  extra: Record<string, unknown> = {},
) => ({
  items,
  shipping: { type: "new", address: testAddress },
  paymentMethod: "CASH_ON_DELIVERY",
  ...extra,
});

async function stockOf(variantId: string) {
  return (await prisma.productVariant.findUniqueOrThrow({ where: { id: variantId } })).stock;
}

describe("placeOrder — cash on delivery", () => {
  it("creates the order, prices it on the server and decrements stock", async () => {
    const user = await signInAs("USER");
    const shirt = await createProduct({
      name: "Oxford Shirt",
      price: "79.00",
      variants: [{ stock: 5 }],
    });
    const tee = await createProduct({ name: "Tee", price: "12.50", variants: [{ stock: 3 }] });
    const shirtVariant = shirt.variants[0]!;
    const teeVariant = tee.variants[0]!;

    const result = await placeOrder(
      cod([
        { variantId: shirtVariant.id, quantity: 1 },
        // A client-supplied price is stripped by the schema and never used.
        { variantId: teeVariant.id, quantity: 2, unitPrice: "0.01" } as never,
      ]),
    );
    if (!result.ok) throw new Error(result.error);

    const order = await prisma.order.findUniqueOrThrow({
      where: { id: result.data.orderId },
      include: { items: { orderBy: { productName: "asc" } } },
    });
    expect(order).toMatchObject({
      userId: user.id,
      status: "PENDING",
      paymentStatus: "PENDING",
      paymentMethod: "CASH_ON_DELIVERY",
      stockDeducted: true,
      shippingCity: "Portland",
    });
    expect(order.subtotal.toFixed(2)).toBe("104.00");
    expect(order.shippingFee.toFixed(2)).toBe("0.00");
    expect(order.total.toFixed(2)).toBe("104.00");
    expect(order.items.map((i) => [i.productName, i.unitPrice.toFixed(2), i.quantity])).toEqual([
      ["Oxford Shirt", "79.00", 1],
      ["Tee", "12.50", 2],
    ]);
    expect(await stockOf(shirtVariant.id)).toBe(4);
    expect(await stockOf(teeVariant.id)).toBe(1);
    expect(result.data.redirectUrl).toBe(`/checkout/success?order=${order.id}`);
  });

  it("adds flat shipping below the free-shipping threshold", async () => {
    await signInAs("USER");
    const tee = await createProduct({ price: "30.00" });
    const result = await placeOrder(cod([{ variantId: tee.variants[0]!.id, quantity: 1 }]));
    if (!result.ok) throw new Error(result.error);
    const order = await prisma.order.findUniqueOrThrow({ where: { id: result.data.orderId } });
    expect(order.shippingFee.toFixed(2)).toBe("10.00");
    expect(order.total.toFixed(2)).toBe("40.00");
  });

  it("rolls back everything when any item is out of stock", async () => {
    await signInAs("USER");
    const plenty = await createProduct({ name: "Plenty", variants: [{ stock: 10 }] });
    const scarce = await createProduct({ name: "Scarce", variants: [{ stock: 1 }] });

    const result = await placeOrder(
      cod([
        { variantId: plenty.variants[0]!.id, quantity: 2 },
        { variantId: scarce.variants[0]!.id, quantity: 3 },
      ]),
    );
    expect(result).toMatchObject({ ok: false, error: expect.stringContaining("Scarce") });
    expect(await prisma.order.count()).toBe(0);
    expect(await stockOf(plenty.variants[0]!.id)).toBe(10);
    expect(await stockOf(scarce.variants[0]!.id)).toBe(1);
  });

  it("never oversells when two customers race for the last unit", async () => {
    const last = await createProduct({ variants: [{ stock: 1 }] });
    const variantId = last.variants[0]!.id;
    const [alice, bob] = await Promise.all([signUpUser(), signUpUser()]);

    actAs(alice);
    const first = placeOrder(cod([{ variantId, quantity: 1 }]));
    actAs(bob);
    const second = placeOrder(cod([{ variantId, quantity: 1 }]));
    const results = await Promise.all([first, second]);

    expect(results.filter((r) => r.ok)).toHaveLength(1);
    expect(await prisma.order.count()).toBe(1);
    expect(await stockOf(variantId)).toBe(0);
  });

  it("rejects archived products", async () => {
    await signInAs("USER");
    const archived = await createProduct({ isArchived: true });
    const result = await placeOrder(cod([{ variantId: archived.variants[0]!.id, quantity: 1 }]));
    expect(result).toMatchObject({ ok: false });
    expect(await prisma.order.count()).toBe(0);
  });

  it("uses a saved address only when it belongs to the customer", async () => {
    const owner = await signUpUser();
    const stranger = await signUpUser();
    const address = await createAddress(owner.user.id, true);
    const product = await createProduct();
    const input = {
      items: [{ variantId: product.variants[0]!.id, quantity: 1 }],
      shipping: { type: "saved", addressId: address.id },
      paymentMethod: "CASH_ON_DELIVERY",
    };

    actAs(stranger);
    expect(await placeOrder(input)).toMatchObject({ ok: false });

    actAs(owner);
    const result = await placeOrder(input);
    expect(result.ok).toBe(true);
  });

  it("saves a new address when asked, as the default for a first address", async () => {
    const user = await signInAs("USER");
    const product = await createProduct();
    await placeOrder(
      cod([{ variantId: product.variants[0]!.id, quantity: 1 }], {
        shipping: { type: "new", address: testAddress, saveAddress: true },
      }),
    );
    const saved = await prisma.address.findMany({ where: { userId: user.id } });
    expect(saved).toHaveLength(1);
    expect(saved[0]?.isDefault).toBe(true);
  });

  it("requires a signed-in customer", async () => {
    actAs(null);
    const product = await createProduct();
    expect(await placeOrder(cod([{ variantId: product.variants[0]!.id, quantity: 1 }]))).toEqual({
      ok: false,
      error: "You need to sign in.",
    });
  });

  it("returns field errors for invalid input", async () => {
    await signInAs("USER");
    const result = await placeOrder({
      items: [],
      shipping: { type: "new", address: { ...testAddress, postalCode: "" } },
      paymentMethod: "CASH_ON_DELIVERY",
    });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.fieldErrors?.["shipping.address.postalCode"]).toBeDefined();
    expect(result.fieldErrors?.items).toBeDefined();
  });

  it("rate-limits repeated attempts", async () => {
    await signInAs("USER");
    const product = await createProduct({ variants: [{ stock: 100 }] });
    const input = cod([{ variantId: product.variants[0]!.id, quantity: 1 }]);
    for (let i = 0; i < RATE_LIMITS.placeOrder.max; i++) {
      expect((await placeOrder(input)).ok).toBe(true);
    }
    expect(await placeOrder(input)).toMatchObject({
      ok: false,
      error: expect.stringContaining("Too many checkout attempts"),
    });
  });
});
