import type { MetadataRoute } from "next";

import { env } from "@/env";
import { Category } from "@/generated/prisma/enums";
import { categoryHref } from "@/lib/navigation";
import { getSitemapProducts } from "@/server/queries/catalog";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const base = env.NEXT_PUBLIC_APP_URL;
  const products = await getSitemapProducts();
  return [
    { url: `${base}/`, changeFrequency: "daily", priority: 1 },
    { url: `${base}/shop`, changeFrequency: "daily", priority: 0.9 },
    ...Object.values(Category).map((category) => ({
      url: `${base}${categoryHref(category)}`,
      changeFrequency: "daily" as const,
      priority: 0.8,
    })),
    ...products.map((product) => ({
      url: `${base}/products/${product.slug}`,
      lastModified: product.updatedAt,
      changeFrequency: "weekly" as const,
      priority: 0.7,
    })),
  ];
}
