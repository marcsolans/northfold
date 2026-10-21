import type { ShopFilters } from "./validators/catalog";

export type ShopUrlState = Omit<ShopFilters, "page"> & { page?: number };

/**
 * Builds a canonical /shop URL from filter state. Defaults are omitted so URLs stay short and
 * shareable; enum values are lowercased for readability (parsing is case-insensitive).
 */
export function shopHref(state: Partial<ShopUrlState>): string {
  const params = new URLSearchParams();
  if (state.q) params.set("q", state.q);
  for (const value of state.category ?? []) params.append("category", value.toLowerCase());
  for (const value of state.type ?? []) params.append("type", value.toLowerCase());
  for (const value of state.size ?? []) params.append("size", value);
  if (state.minPrice !== undefined) params.set("minPrice", String(state.minPrice));
  if (state.maxPrice !== undefined) params.set("maxPrice", String(state.maxPrice));
  if (state.inStock) params.set("inStock", "1");
  if (state.sort && state.sort !== "newest") params.set("sort", state.sort);
  if (state.page && state.page > 1) params.set("page", String(state.page));
  const query = params.toString();
  return query ? `/shop?${query}` : "/shop";
}

/** Adds the value if absent, removes it if present. */
export function toggleValue<T>(values: readonly T[], value: T): T[] {
  return values.includes(value) ? values.filter((v) => v !== value) : [...values, value];
}

export function hasActiveFilters(state: Partial<ShopUrlState>): boolean {
  return Boolean(
    state.q ||
    state.category?.length ||
    state.type?.length ||
    state.size?.length ||
    state.minPrice !== undefined ||
    state.maxPrice !== undefined ||
    state.inStock,
  );
}
