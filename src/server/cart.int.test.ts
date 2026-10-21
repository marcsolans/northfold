import { beforeEach, describe, expect, it } from "vitest";

import { prisma, resetDatabase } from "../../tests/db";
import { createProduct } from "../../tests/factories";

import { validateCart } from "./actions/cart";

beforeEach(resetDatabase);

describe("validateCart", () => {
  it("refreshes snapshots from the database and keeps valid lines", async () => {
    const product = await createProduct({ price: "49.00", variants: [{ stock: 5 }] });
    const variant = product.variants[0]!;
    const result = await validateCart([
      { variantId: variant.id, quantity: 2, knownPrice: "49.00" },
    ]);
    expect(result).toMatchObject({
      ok: true,
      data: {
        changes: [],
        lines: [
          { variantId: variant.id, quantity: 2, snapshot: { unitPrice: "49.00", available: 5 } },
        ],
      },
    });
  });

  it("removes archived, deleted and sold-out items and says why", async () => {
    const archived = await createProduct({ isArchived: true });
    const soldOut = await createProduct({ name: "Sold Out Tee", variants: [{ stock: 0 }] });
    const result = await validateCart([
      { variantId: archived.variants[0]!.id, quantity: 1, label: "Archived thing" },
      { variantId: soldOut.variants[0]!.id, quantity: 1 },
      { variantId: "missing-variant", quantity: 1, label: "Ghost item" },
    ]);
    if (!result.ok) throw new Error(result.error);
    expect(result.data.lines).toEqual([]);
    expect(result.data.changes).toEqual([
      { type: "removed", label: "Archived thing", reason: "unavailable" },
      { type: "removed", label: expect.stringContaining("Sold Out Tee"), reason: "sold_out" },
      { type: "removed", label: "Ghost item", reason: "unavailable" },
    ]);
  });

  it("clamps quantities to stock and reports price changes", async () => {
    const product = await createProduct({ price: "30.00", variants: [{ stock: 2 }] });
    const variant = product.variants[0]!;
    await prisma.product.update({ where: { id: product.id }, data: { price: "35.50" } });
    const result = await validateCart([
      { variantId: variant.id, quantity: 5, knownPrice: "30.00" },
    ]);
    if (!result.ok) throw new Error(result.error);
    expect(result.data.lines[0]).toMatchObject({ quantity: 2, snapshot: { unitPrice: "35.50" } });
    expect(result.data.changes).toEqual([
      expect.objectContaining({ type: "quantity_reduced", from: 5, to: 2 }),
      expect.objectContaining({ type: "price_changed", from: "30.00", to: "35.50" }),
    ]);
  });

  it("never trusts a client price, even when it claims to be current", async () => {
    const product = await createProduct({ price: "80.00" });
    const result = await validateCart([
      { variantId: product.variants[0]!.id, quantity: 1, knownPrice: "0.01" },
    ]);
    if (!result.ok) throw new Error(result.error);
    expect(result.data.lines[0]?.snapshot.unitPrice).toBe("80.00");
  });

  it("rejects malformed input with a safe error", async () => {
    const result = await validateCart([{ variantId: "x", quantity: -3 }]);
    expect(result).toEqual({ ok: false, error: expect.any(String) });
    expect(await validateCart("not an array")).toMatchObject({ ok: false });
  });
});
