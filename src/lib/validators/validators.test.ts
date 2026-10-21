import { describe, expect, it } from "vitest";

import { addressSchema } from "./address";
import { changePasswordSchema, safeRedirectPath, signInSchema, signUpSchema } from "./auth";
import { cartLinesSchema } from "./cart";
import { parseShopFilters } from "./catalog";
import { checkoutFormSchema, EMPTY_ADDRESS, placeOrderSchema, toPlaceOrderInput } from "./checkout";
import { productFormSchema } from "./product";

const validAddress = {
  fullName: "Ada Lovelace",
  phone: "+1 (555) 010-2030",
  line1: "12 Analytical Way",
  city: "Portland",
  state: "OR",
  postalCode: "97201",
  country: "US",
};

describe("auth schemas", () => {
  it("normalises emails", () => {
    const parsed = signInSchema.parse({ email: "  Ada@Example.COM ", password: "x" });
    expect(parsed.email).toBe("ada@example.com");
  });

  it("requires matching passwords on sign-up", () => {
    const result = signUpSchema.safeParse({
      name: "Ada",
      email: "ada@example.com",
      password: "correct-horse",
      confirmPassword: "wrong-horse",
    });
    expect(result.success).toBe(false);
    expect(result.error?.issues[0]?.path).toEqual(["confirmPassword"]);
  });

  it("enforces a minimum password length", () => {
    const result = signUpSchema.safeParse({
      name: "Ada",
      email: "ada@example.com",
      password: "short",
      confirmPassword: "short",
    });
    expect(result.success).toBe(false);
  });

  it("rejects reusing the current password", () => {
    const result = changePasswordSchema.safeParse({
      currentPassword: "same-password",
      newPassword: "same-password",
      confirmPassword: "same-password",
    });
    expect(result.success).toBe(false);
  });

  it.each([
    ["/checkout", "/checkout"],
    ["/account/orders?page=2", "/account/orders?page=2"],
    ["//evil.com", "/"],
    ["https://evil.com", "/"],
    ["/\\evil.com", "/"],
    [undefined, "/"],
  ])("safeRedirectPath(%s) → %s", (input, expected) => {
    expect(safeRedirectPath(input)).toBe(expected);
  });
});

describe("addressSchema", () => {
  it("accepts a valid address and drops an empty line2", () => {
    const parsed = addressSchema.parse({ ...validAddress, line2: "  " });
    expect(parsed.line2).toBeUndefined();
  });

  it("rejects unsupported countries and bad phones", () => {
    expect(addressSchema.safeParse({ ...validAddress, country: "XX" }).success).toBe(false);
    expect(addressSchema.safeParse({ ...validAddress, phone: "call me" }).success).toBe(false);
  });
});

describe("cartLinesSchema", () => {
  it("rejects duplicate variants and out-of-range quantities", () => {
    expect(
      cartLinesSchema.safeParse([
        { variantId: "a", quantity: 1 },
        { variantId: "a", quantity: 2 },
      ]).success,
    ).toBe(false);
    expect(cartLinesSchema.safeParse([{ variantId: "a", quantity: 0 }]).success).toBe(false);
    expect(cartLinesSchema.safeParse([{ variantId: "a", quantity: 1.5 }]).success).toBe(false);
  });
});

describe("placeOrderSchema", () => {
  it("accepts a new address with COD", () => {
    const parsed = placeOrderSchema.parse({
      items: [{ variantId: "v1", quantity: 2 }],
      shipping: { type: "new", address: validAddress },
      paymentMethod: "CASH_ON_DELIVERY",
    });
    expect(parsed.shipping.type === "new" && parsed.shipping.saveAddress).toBe(false);
  });

  it("rejects an empty cart and unknown payment methods", () => {
    expect(
      placeOrderSchema.safeParse({
        items: [],
        shipping: { type: "saved", addressId: "addr1" },
        paymentMethod: "STRIPE",
      }).success,
    ).toBe(false);
    expect(
      placeOrderSchema.safeParse({
        items: [{ variantId: "v1", quantity: 1 }],
        shipping: { type: "saved", addressId: "addr1" },
        paymentMethod: "BITCOIN",
      }).success,
    ).toBe(false);
  });

  it("ignores client-supplied prices", () => {
    const parsed = placeOrderSchema.parse({
      items: [{ variantId: "v1", quantity: 1, unitPrice: "0.01" }],
      shipping: { type: "saved", addressId: "addr1" },
      paymentMethod: "STRIPE",
    });
    expect(parsed.items[0]).toEqual({ variantId: "v1", quantity: 1 });
  });
});

describe("parseShopFilters", () => {
  it("parses multi-value filters and ignores unknown values", () => {
    const filters = parseShopFilters({
      category: "men",
      size: ["S", "m,XXXL"],
      type: "hoodie,unknown",
      sort: "price-asc",
      page: "2",
      inStock: "1",
    });
    expect(filters).toMatchObject({
      category: ["MEN"],
      size: ["S", "M"],
      type: ["HOODIE"],
      sort: "price-asc",
      page: 2,
      inStock: true,
    });
  });

  it("falls back to defaults for garbage input", () => {
    const filters = parseShopFilters({ sort: "cheapest", page: "-4", minPrice: "abc" });
    expect(filters.sort).toBe("newest");
    expect(filters.page).toBe(1);
    expect(filters.minPrice).toBeUndefined();
  });

  it("swaps an inverted price range", () => {
    const filters = parseShopFilters({ minPrice: "120", maxPrice: "40" });
    expect(filters.minPrice).toBe(40);
    expect(filters.maxPrice).toBe(120);
  });

  it("trims and caps the search query", () => {
    expect(parseShopFilters({ q: "  linen  " }).q).toBe("linen");
    expect(parseShopFilters({ q: "   " }).q).toBeUndefined();
  });
});

describe("productFormSchema", () => {
  const product = {
    name: "Linen Shirt",
    slug: "linen-shirt",
    description: "Breathable linen.",
    price: "79.00",
    category: "MEN",
    productType: "SHIRT",
    isFeatured: false,
    isBestseller: false,
    isArchived: false,
    images: [
      { url: "https://res.cloudinary.com/demo/image/upload/a.jpg", publicId: "a", alt: "Shirt" },
    ],
    variants: [
      { size: "M", colorName: "Sand", colorHex: "#d8c8a8", sku: "nf-lin-m-sand", stock: "4" },
      { size: "L", colorName: "Sand", colorHex: "#d8c8a8", sku: "NF-LIN-L-SAND", stock: 0 },
    ],
  };

  it("accepts a valid product and normalises SKUs and stock", () => {
    const parsed = productFormSchema.parse(product);
    expect(parsed.variants[0]?.sku).toBe("NF-LIN-M-SAND");
    expect(parsed.variants[0]?.stock).toBe(4);
  });

  it("rejects duplicate size/colour combinations and SKUs", () => {
    const result = productFormSchema.safeParse({
      ...product,
      variants: [product.variants[0], { ...product.variants[0] }],
    });
    expect(result.success).toBe(false);
    const paths = result.error?.issues.map((issue) => issue.path.join("."));
    expect(paths).toContain("variants.1.colorName");
    expect(paths).toContain("variants.1.sku");
  });

  it("rejects negative stock, zero prices and too many images", () => {
    expect(
      productFormSchema.safeParse({
        ...product,
        variants: [{ ...product.variants[0], stock: -1 }],
      }).success,
    ).toBe(false);
    expect(productFormSchema.safeParse({ ...product, price: "0" }).success).toBe(false);
    expect(
      productFormSchema.safeParse({ ...product, images: Array(7).fill(product.images[0]) }).success,
    ).toBe(false);
  });
});

describe("checkoutFormSchema", () => {
  const base = {
    shippingChoice: "new",
    address: { ...validAddress, line2: "" },
    saveAddress: true,
    paymentMethod: "CASH_ON_DELIVERY",
  } as const;

  it("validates a new address with the shared address rules", () => {
    expect(checkoutFormSchema.safeParse(base).success).toBe(true);
    const bad = checkoutFormSchema.safeParse({ ...base, address: { ...base.address, phone: "x" } });
    expect(bad.error?.issues[0]?.path).toEqual(["address", "phone"]);
  });

  it("ignores the address fields when a saved address is chosen", () => {
    const parsed = checkoutFormSchema.safeParse({
      ...base,
      shippingChoice: "addr_1",
      address: EMPTY_ADDRESS,
    });
    expect(parsed.success).toBe(true);
  });

  it("maps to a placeOrder payload the server schema accepts", () => {
    const items = [{ variantId: "v1", quantity: 2 }];
    const values = checkoutFormSchema.parse(base);
    expect(placeOrderSchema.safeParse(toPlaceOrderInput(values, items)).success).toBe(true);
    const saved = toPlaceOrderInput({ ...values, shippingChoice: "addr_9" }, items);
    expect(saved.shipping).toEqual({ type: "saved", addressId: "addr_9" });
  });
});
