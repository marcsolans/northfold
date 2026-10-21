import { beforeEach, describe, expect, it } from "vitest";

import { CATALOG } from "@/lib/store-config";

import {
  CART_STORAGE_KEY,
  type CartSnapshot,
  selectItemCount,
  selectTotals,
  useCartStore,
} from "./cart-store";

const snapshot = (overrides: Partial<CartSnapshot> = {}): CartSnapshot => ({
  productId: "p1",
  productName: "Linen Shirt",
  productSlug: "linen-shirt",
  imageUrl: null,
  size: "M",
  colorName: "Sand",
  unitPrice: "40.00",
  available: 5,
  ...overrides,
});

const store = () => useCartStore.getState();

beforeEach(() => {
  localStorage.clear();
  useCartStore.setState(useCartStore.getInitialState(), true);
});

describe("cart store", () => {
  it("adds items and merges repeated adds of the same variant", () => {
    store().addItem("v1", snapshot(), 1);
    store().addItem("v1", snapshot(), 2);
    expect(store().lines).toHaveLength(1);
    expect(store().lines[0]?.quantity).toBe(3);
  });

  it("caps quantities at available stock and the per-line maximum", () => {
    store().addItem("v1", snapshot({ available: 2 }), 5);
    expect(store().lines[0]?.quantity).toBe(2);
    store().addItem("v2", snapshot({ available: 999 }), 999);
    expect(store().lines[1]?.quantity).toBe(CATALOG.maxQuantityPerLine);
  });

  it("ignores adds of sold-out items", () => {
    store().addItem("v1", snapshot({ available: 0 }), 1);
    expect(store().lines).toEqual([]);
  });

  it("updates quantities, removing the line at zero", () => {
    store().addItem("v1", snapshot(), 2);
    store().setQuantity("v1", 4);
    expect(store().lines[0]?.quantity).toBe(4);
    store().setQuantity("v1", 99);
    expect(store().lines[0]?.quantity).toBe(5);
    store().setQuantity("v1", 0);
    expect(store().lines).toEqual([]);
  });

  it("removes a line and clears the cart", () => {
    store().addItem("v1", snapshot(), 1);
    store().addItem("v2", snapshot(), 1);
    store().removeItem("v1");
    expect(store().lines.map((l) => l.variantId)).toEqual(["v2"]);
    store().clear();
    expect(store().lines).toEqual([]);
  });

  it("replaces lines with server-validated ones", () => {
    store().addItem("v1", snapshot(), 3);
    store().replaceLines([
      { variantId: "v1", quantity: 1, snapshot: snapshot({ unitPrice: "35.00" }) },
    ]);
    expect(store().lines[0]).toMatchObject({ quantity: 1, snapshot: { unitPrice: "35.00" } });
  });

  it("counts items and computes totals with the shipping threshold", () => {
    store().addItem("v1", snapshot({ unitPrice: "40.00" }), 2);
    expect(selectItemCount(store())).toBe(2);
    expect(selectTotals(store()).shippingFee.toFixed(2)).toBe("10.00");
    expect(selectTotals(store()).total.toFixed(2)).toBe("90.00");
    store().addItem("v2", snapshot({ unitPrice: "20.00" }), 1);
    expect(selectTotals(store()).shippingFee.toFixed(2)).toBe("0.00");
    expect(selectTotals(store()).total.toFixed(2)).toBe("100.00");
  });

  it("persists only the lines to localStorage and rehydrates them", async () => {
    store().addItem("v1", snapshot(), 2);
    const raw = localStorage.getItem(CART_STORAGE_KEY) ?? "{}";
    const persisted = JSON.parse(raw) as { state: Record<string, unknown>; version: number };
    expect(Object.keys(persisted.state)).toEqual(["lines"]);
    expect(persisted.version).toBe(1);

    // Simulate a fresh page load: empty in-memory state, previously saved storage.
    useCartStore.setState(useCartStore.getInitialState(), true);
    localStorage.setItem(CART_STORAGE_KEY, raw);
    expect(store().lines).toEqual([]);
    await useCartStore.persist.rehydrate();
    expect(store().lines[0]?.quantity).toBe(2);
  });
});
