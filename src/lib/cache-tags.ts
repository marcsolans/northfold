/**
 * Cache tags used with `cacheTag()` in queries and `updateTag()` / `revalidateTag()` after
 * mutations. Keep them id/slug based: tags are stored as plain text.
 */
export const CACHE_TAGS = {
  /** Every catalog read (listings, search, product pages). */
  products: "products",
  product: (slug: string) => `product:${slug}`,
} as const;
