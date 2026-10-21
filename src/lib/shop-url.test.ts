import { describe, expect, it } from "vitest";

import { hasActiveFilters, shopHref, toggleValue } from "./shop-url";
import { parseShopFilters } from "./validators/catalog";

describe("shopHref", () => {
  it("omits defaults", () => {
    expect(shopHref({})).toBe("/shop");
    expect(shopHref({ sort: "newest", page: 1, inStock: false })).toBe("/shop");
  });

  it("encodes multi-value filters as repeated params", () => {
    expect(shopHref({ category: ["MEN", "WOMEN"], size: ["S", "M"], inStock: true })).toBe(
      "/shop?category=men&category=women&size=S&size=M&inStock=1",
    );
  });

  it("round-trips through the parser", () => {
    const original = parseShopFilters({
      q: "linen shirt",
      category: "women",
      type: ["shirt", "tshirt"],
      size: "XS",
      minPrice: "20",
      maxPrice: "150",
      inStock: "1",
      sort: "price-desc",
      page: "3",
    });
    const url = new URL(shopHref(original), "http://localhost");
    const params: Record<string, string[]> = {};
    url.searchParams.forEach((value, key) => {
      params[key] = [...(params[key] ?? []), value];
    });
    expect(parseShopFilters(params)).toEqual(original);
  });
});

describe("toggleValue", () => {
  it("adds and removes values", () => {
    expect(toggleValue(["S"], "M")).toEqual(["S", "M"]);
    expect(toggleValue(["S", "M"], "S")).toEqual(["M"]);
  });
});

describe("hasActiveFilters", () => {
  it("ignores sort and page", () => {
    expect(hasActiveFilters({ sort: "price-asc", page: 2 })).toBe(false);
    expect(hasActiveFilters({ size: ["M"] })).toBe(true);
    expect(hasActiveFilters({ minPrice: 0 })).toBe(true);
  });
});
