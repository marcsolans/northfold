import { beforeEach, describe, expect, it } from "vitest";

import { prisma, resetDatabase } from "../../tests/db";
import { createProduct } from "../../tests/factories";

import { money } from "./money";

beforeEach(resetDatabase);

describe("database constraints", () => {
  it("rejects negative stock with a CHECK constraint", async () => {
    const product = await createProduct({ variants: [{ stock: 1 }] });
    const variant = product.variants[0];
    if (!variant) throw new Error("variant missing");
    await expect(
      prisma.productVariant.update({ where: { id: variant.id }, data: { stock: -1 } }),
    ).rejects.toThrow();
  });

  it("supports conditional stock decrements that never oversell", async () => {
    const product = await createProduct({ variants: [{ stock: 2 }] });
    const variant = product.variants[0];
    if (!variant) throw new Error("variant missing");
    const decrement = () =>
      prisma.productVariant.updateMany({
        where: { id: variant.id, stock: { gte: 1 } },
        data: { stock: { decrement: 1 } },
      });
    const results = await Promise.all([decrement(), decrement(), decrement()]);
    expect(results.map((r) => r.count).sort()).toEqual([0, 1, 1]);
    const after = await prisma.productVariant.findUniqueOrThrow({ where: { id: variant.id } });
    expect(after.stock).toBe(0);
  });

  it("round-trips Decimal prices exactly", async () => {
    const product = await createProduct({ price: "19.99" });
    const stored = await prisma.product.findUniqueOrThrow({ where: { id: product.id } });
    expect(money(stored.price).times(3).toFixed(2)).toBe("59.97");
  });

  it("enforces one variant per product, size and colour", async () => {
    await expect(
      createProduct({
        variants: [
          { size: "M", colorName: "Black" },
          { size: "M", colorName: "Black" },
        ],
      }),
    ).rejects.toThrow();
  });
});
