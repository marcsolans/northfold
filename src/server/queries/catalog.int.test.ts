import { beforeEach, describe, expect, it } from "vitest";

import { prisma, resetDatabase } from "../../../tests/db";
import { createProduct } from "../../../tests/factories";
import { parseShopFilters } from "@/lib/validators/catalog";

import {
  escapeLike,
  getBestsellers,
  getProductBySlug,
  getRelatedProducts,
  searchProducts,
} from "./catalog";

beforeEach(resetDatabase);

async function seedCatalog() {
  const linenShirt = await createProduct({
    name: "Linen Camp Shirt",
    price: "85.00",
    category: "MEN",
    productType: "SHIRT",
    variants: [
      { size: "M", colorName: "Sand", stock: 0 },
      { size: "L", colorName: "Sand", stock: 4 },
    ],
  });
  const tee = await createProduct({
    name: "Essential Tee",
    price: "32.00",
    category: "MEN",
    productType: "TSHIRT",
    variants: [{ size: "M", colorName: "White", stock: 10 }],
  });
  const coat = await createProduct({
    name: "Wool Coat",
    price: "320.00",
    category: "WOMEN",
    productType: "JACKET",
    variants: [{ size: "S", colorName: "Camel", stock: 0 }],
  });
  const archived = await createProduct({
    name: "Old Linen Trousers",
    price: "99.00",
    category: "MEN",
    productType: "TROUSERS",
    isArchived: true,
  });
  return { linenShirt, tee, coat, archived };
}

const search = (params: Record<string, string | string[]>) =>
  searchProducts(parseShopFilters(params));

describe("searchProducts", () => {
  it("excludes archived products", async () => {
    await seedCatalog();
    const result = await search({});
    expect(result.products.map((p) => p.name)).not.toContain("Old Linen Trousers");
    expect(result.total).toBe(3);
  });

  it("filters by category and product type", async () => {
    await seedCatalog();
    expect((await search({ category: "men" })).total).toBe(2);
    expect((await search({ category: "men", type: "tshirt" })).products[0]?.name).toBe(
      "Essential Tee",
    );
  });

  it("matches size and stock on the same variant", async () => {
    await seedCatalog();
    // The shirt has size M, but M is sold out: it must not match "M, in stock".
    const result = await search({ size: "M", inStock: "1" });
    expect(result.products.map((p) => p.name)).toEqual(["Essential Tee"]);
    // Without the stock filter both products with an M variant match.
    expect((await search({ size: "M" })).total).toBe(2);
  });

  it("filters out fully sold-out products when in-stock only", async () => {
    await seedCatalog();
    const names = (await search({ inStock: "1" })).products.map((p) => p.name);
    expect(names).not.toContain("Wool Coat");
  });

  it("filters by price range (inclusive)", async () => {
    await seedCatalog();
    const names = (await search({ minPrice: "32", maxPrice: "85" })).products.map((p) => p.name);
    expect(names.sort()).toEqual(["Essential Tee", "Linen Camp Shirt"]);
  });

  it("searches name and description case-insensitively", async () => {
    await seedCatalog();
    expect((await search({ q: "LINEN" })).products.map((p) => p.name)).toEqual([
      "Linen Camp Shirt",
    ]);
    expect((await search({ q: "product used in tests" })).total).toBe(3);
  });

  it("treats LIKE wildcards in the query literally", async () => {
    await seedCatalog();
    expect((await search({ q: "%" })).total).toBe(0);
    expect((await search({ q: "_" })).total).toBe(0);
    expect(escapeLike("50%_off\\")).toBe("50\\%\\_off\\\\");
  });

  it("sorts by price in both directions", async () => {
    await seedCatalog();
    const asc = (await search({ sort: "price-asc" })).products.map((p) => p.price);
    expect(asc).toEqual(["32.00", "85.00", "320.00"]);
    const desc = (await search({ sort: "price-desc" })).products.map((p) => p.price);
    expect(desc).toEqual(["320.00", "85.00", "32.00"]);
  });

  it("paginates and clamps the page to the last one", async () => {
    for (let i = 0; i < 14; i++) await createProduct({ name: `Paged ${i}` });
    const first = await search({});
    expect(first.products).toHaveLength(12);
    expect(first.totalPages).toBe(2);
    const second = await search({ page: "2" });
    expect(second.products).toHaveLength(2);
    const beyond = await search({ page: "9" });
    expect(beyond.page).toBe(2);
  });

  it("exposes prices as fixed two-decimal strings", async () => {
    await createProduct({ price: "19.9" });
    expect((await search({})).products[0]?.price).toBe("19.90");
  });
});

describe("product queries", () => {
  it("returns a product with its variants, or null when archived", async () => {
    const { linenShirt, archived } = await seedCatalog();
    const detail = await getProductBySlug(linenShirt.slug);
    expect(detail?.variants).toHaveLength(2);
    expect(detail?.inStock).toBe(true);
    expect(await getProductBySlug(archived.slug)).toBeNull();
    expect(await getProductBySlug("does-not-exist")).toBeNull();
  });

  it("finds related products in the same category, excluding the product itself", async () => {
    const { linenShirt, tee } = await seedCatalog();
    const related = await getRelatedProducts(linenShirt);
    expect(related.map((p) => p.id)).toEqual([tee.id]);
  });

  it("lists bestsellers only", async () => {
    const { tee } = await seedCatalog();
    await prisma.product.update({ where: { id: tee.id }, data: { isBestseller: true } });
    expect((await getBestsellers()).map((p) => p.id)).toEqual([tee.id]);
  });
});
