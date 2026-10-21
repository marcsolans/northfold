import { z } from "zod";

import { Category, ProductType, Size } from "@/generated/prisma/enums";

import { firstParam, pageSchema, rawParam, type RawParam } from "./common";

export const SORT_OPTIONS = ["newest", "price-asc", "price-desc"] as const;
export type SortOption = (typeof SORT_OPTIONS)[number];

/** Accepts `?size=S&size=M` and `?size=S,M`; drops anything that is not a known value. */
function multiEnum<const T extends readonly string[]>(values: T) {
  const allowed = new Set<string>(values);
  return rawParam.transform((raw) => {
    const list = (Array.isArray(raw) ? raw : raw ? [raw] : []).flatMap((v) => v.split(","));
    const normalised = list.map((v) => v.trim().toUpperCase());
    return [...new Set(normalised)].filter((v): v is T[number] => allowed.has(v));
  });
}

const optionalPrice = rawParam.transform((raw) => {
  const value = firstParam(raw);
  if (value === undefined || value.trim() === "") return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 && parsed <= 100_000
    ? Math.floor(parsed)
    : undefined;
});

function isSortOption(value: string | undefined): value is SortOption {
  return (SORT_OPTIONS as readonly (string | undefined)[]).includes(value);
}

/**
 * Parses the shop's URL search params. Invalid values are ignored rather than rejected, so a
 * hand-edited or stale URL still renders a sensible page.
 */
export const shopFiltersSchema = z
  .object({
    q: rawParam.transform((raw) => firstParam(raw)?.trim().slice(0, 100) || undefined),
    category: multiEnum(Object.values(Category)),
    type: multiEnum(Object.values(ProductType)),
    size: multiEnum(Object.values(Size)),
    minPrice: optionalPrice,
    maxPrice: optionalPrice,
    inStock: rawParam.transform((raw) => ["1", "true"].includes(firstParam(raw) ?? "")),
    sort: rawParam.transform((raw): SortOption => {
      const value = firstParam(raw);
      return isSortOption(value) ? value : "newest";
    }),
    page: rawParam.transform((raw) => pageSchema.parse(firstParam(raw))),
  })
  .transform((filters) =>
    filters.minPrice !== undefined &&
    filters.maxPrice !== undefined &&
    filters.minPrice > filters.maxPrice
      ? { ...filters, minPrice: filters.maxPrice, maxPrice: filters.minPrice }
      : filters,
  );

export type ShopFilters = z.output<typeof shopFiltersSchema>;

export function parseShopFilters(searchParams: Record<string, RawParam>): ShopFilters {
  return shopFiltersSchema.parse(searchParams);
}
