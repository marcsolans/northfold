import { beforeEach, describe, expect, it } from "vitest";

import { signInAs, signUpUser } from "../../../../tests/auth";
import { prisma, resetDatabase } from "../../../../tests/db";
import { createProduct as createProductRow, testAddress } from "../../../../tests/factories";

import { placeOrder } from "../checkout";

import { createProduct, deleteProduct, setProductArchived, updateProduct } from "./products";

beforeEach(resetDatabase);

const form = (overrides: Record<string, unknown> = {}) => ({
  name: "Merino Rollneck",
  slug: "merino-rollneck",
  description: "Fine merino wool.",
  price: "120.00",
  category: "MEN",
  productType: "HOODIE",
  isFeatured: true,
  isBestseller: false,
  isArchived: false,
  images: [
    { url: "https://images.unsplash.com/photo-1", publicId: null, alt: "Rollneck on a hanger" },
  ],
  variants: [
    { size: "M", colorName: "Oat", colorHex: "#e3d9c6", sku: "nf-mer-m-oat", stock: 4 },
    { size: "L", colorName: "Oat", colorHex: "#e3d9c6", sku: "NF-MER-L-OAT", stock: 0 },
  ],
  ...overrides,
});

describe("createProduct", () => {
  it("creates the product with ordered images and variants", async () => {
    await signInAs("ADMIN");
    const result = await createProduct(form());
    if (!result.ok) throw new Error(result.error);
    const product = await prisma.product.findUniqueOrThrow({
      where: { id: result.data.id },
      include: { images: true, variants: { orderBy: { sku: "asc" } } },
    });
    expect(product).toMatchObject({ slug: "merino-rollneck", isFeatured: true });
    expect(product.price.toFixed(2)).toBe("120.00");
    expect(product.variants.map((v) => [v.sku, v.stock])).toEqual([
      ["NF-MER-L-OAT", 0],
      ["NF-MER-M-OAT", 4],
    ]);
    expect(product.images[0]).toMatchObject({ position: 0, alt: "Rollneck on a hanger" });
  });

  it("returns field errors for invalid input and disallowed image hosts", async () => {
    await signInAs("ADMIN");
    const result = await createProduct(
      form({
        price: "-5",
        images: [{ url: "https://evil.example.com/x.jpg", publicId: null, alt: "x" }],
      }),
    );
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(Object.keys(result.fieldErrors ?? {})).toEqual(
      expect.arrayContaining(["price", "images.0.url"]),
    );
  });

  it("reports a duplicate slug or SKU as a field error", async () => {
    await signInAs("ADMIN");
    await createProduct(form());
    expect(await createProduct(form({ name: "Other" }))).toMatchObject({
      ok: false,
      fieldErrors: { slug: expect.any(Array) },
    });
    expect(await createProduct(form({ slug: "other-slug" }))).toMatchObject({
      ok: false,
      fieldErrors: { variants: expect.any(Array) },
    });
  });
});

describe("updateProduct", () => {
  it("updates fields, replaces images and adds, edits and removes variants", async () => {
    await signInAs("ADMIN");
    const created = await createProduct(form());
    if (!created.ok) throw new Error(created.error);
    const existing = await prisma.productVariant.findMany({
      where: { productId: created.data.id },
      orderBy: { sku: "asc" },
    });
    const [large, medium] = existing;

    const result = await updateProduct(
      created.data.id,
      form({
        name: "Merino Rollneck Jumper",
        price: "110.00",
        images: [
          { url: "https://images.unsplash.com/photo-2", publicId: null, alt: "Second" },
          { url: "https://images.unsplash.com/photo-1", publicId: null, alt: "First" },
        ],
        variants: [
          {
            id: medium!.id,
            size: "M",
            colorName: "Oat",
            colorHex: "#e3d9c6",
            sku: "NF-MER-M-OAT",
            stock: 9,
          },
          { size: "S", colorName: "Charcoal", colorHex: "#2b2b29", sku: "NF-MER-S-CHR", stock: 3 },
        ],
      }),
    );
    expect(result.ok).toBe(true);

    const product = await prisma.product.findUniqueOrThrow({
      where: { id: created.data.id },
      include: { images: { orderBy: { position: "asc" } }, variants: { orderBy: { sku: "asc" } } },
    });
    expect(product.name).toBe("Merino Rollneck Jumper");
    expect(product.images.map((i) => i.alt)).toEqual(["Second", "First"]);
    expect(product.variants.map((v) => [v.sku, v.stock])).toEqual([
      ["NF-MER-M-OAT", 9],
      ["NF-MER-S-CHR", 3],
    ]);
    expect(await prisma.productVariant.findUnique({ where: { id: large!.id } })).toBeNull();
  });

  it("refuses to remove a variant that has been ordered", async () => {
    const product = await createProductRow({
      variants: [
        { size: "M", stock: 5 },
        { size: "L", stock: 5 },
      ],
    });
    const customer = await signUpUser();
    const { actAs } = await import("../../../../tests/auth");
    actAs(customer);
    await placeOrder({
      items: [{ variantId: product.variants[0]!.id, quantity: 1 }],
      shipping: { type: "new", address: testAddress },
      paymentMethod: "CASH_ON_DELIVERY",
    });

    await signInAs("ADMIN");
    const keep = product.variants[1]!;
    const result = await updateProduct(
      product.id,
      form({
        slug: product.slug,
        variants: [
          {
            id: keep.id,
            size: keep.size,
            colorName: keep.colorName,
            colorHex: "#000000",
            sku: keep.sku,
            stock: 5,
          },
        ],
      }),
    );
    expect(result).toMatchObject({
      ok: false,
      error: expect.stringContaining("cannot be removed"),
    });
    expect(await prisma.productVariant.count({ where: { productId: product.id } })).toBe(2);
  });
});

describe("archive and delete", () => {
  it("archives and restores", async () => {
    await signInAs("ADMIN");
    const product = await createProductRow();
    await setProductArchived(product.id, true);
    expect((await prisma.product.findUniqueOrThrow({ where: { id: product.id } })).isArchived).toBe(
      true,
    );
    await setProductArchived(product.id, false);
    expect((await prisma.product.findUniqueOrThrow({ where: { id: product.id } })).isArchived).toBe(
      false,
    );
  });

  it("hard-deletes a product that was never ordered", async () => {
    await signInAs("ADMIN");
    const product = await createProductRow();
    expect(await deleteProduct(product.id)).toEqual({ ok: true, data: undefined });
    expect(await prisma.product.count()).toBe(0);
    expect(await prisma.productVariant.count()).toBe(0);
  });

  it("only allows archiving once a product has orders", async () => {
    const product = await createProductRow();
    const { actAs } = await import("../../../../tests/auth");
    actAs(await signUpUser());
    await placeOrder({
      items: [{ variantId: product.variants[0]!.id, quantity: 1 }],
      shipping: { type: "new", address: testAddress },
      paymentMethod: "CASH_ON_DELIVERY",
    });
    await signInAs("ADMIN");
    expect(await deleteProduct(product.id)).toMatchObject({
      ok: false,
      error: expect.stringContaining("archived"),
    });
    expect(await prisma.product.count()).toBe(1);
  });
});
