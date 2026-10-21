import type { Category } from "@/generated/prisma/enums";

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
