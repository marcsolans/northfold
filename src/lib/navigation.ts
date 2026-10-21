import type { Category, ProductType } from "@/generated/prisma/enums";
import type { SortOption } from "@/lib/validators/catalog";

export const CATEGORY_LABELS: Record<Category, string> = {
  MEN: "Men",
  WOMEN: "Women",
  CHILDREN: "Children",
};

export function categoryHref(category: Category): string {
  return `/shop?category=${category.toLowerCase()}`;
}

export const STORE_NAV = [
  { href: "/shop", label: "Shop" },
  { href: categoryHref("MEN"), label: "Men" },
  { href: categoryHref("WOMEN"), label: "Women" },
  { href: categoryHref("CHILDREN"), label: "Children" },
] as const;

export const PRODUCT_TYPE_LABELS: Record<ProductType, string> = {
  TSHIRT: "T-shirts",
  SHIRT: "Shirts",
  HOODIE: "Hoodies & knits",
  JACKET: "Jackets & coats",
  JEANS: "Jeans",
  TROUSERS: "Trousers",
  SHORTS: "Shorts",
  SHOES: "Shoes",
};

export const SORT_LABELS: Record<SortOption, string> = {
  newest: "Newest",
  "price-asc": "Price: low to high",
  "price-desc": "Price: high to low",
};
