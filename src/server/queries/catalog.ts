import "server-only";

import { cacheLife, cacheTag } from "next/cache";

import type { Prisma } from "@/generated/prisma/client";
import type { Category, ProductType, Size } from "@/generated/prisma/enums";
import { CACHE_TAGS } from "@/lib/cache-tags";
import { type MoneyString, toMoneyString } from "@/lib/money";
import { prisma } from "@/lib/prisma";
import { CATALOG } from "@/lib/store-config";
import type { ShopFilters } from "@/lib/validators/catalog";

// ─── DTOs (plain, serialisable: safe to pass to Client Components and to cache) ──

export interface ProductImageDTO {
  url: string;
  alt: string;
}

export interface ProductCardDTO {
  id: string;
  slug: string;
  name: string;
  price: MoneyString;
  category: Category;
  productType: ProductType;
  isBestseller: boolean;
  inStock: boolean;
  images: ProductImageDTO[];
  colors: { name: string; hex: string }[];
}

export interface ProductVariantDTO {
  id: string;
  size: Size;
  colorName: string;
  colorHex: string;
  stock: number;
}

export interface ProductDetailDTO extends ProductCardDTO {
  description: string;
  updatedAt: string;
  variants: ProductVariantDTO[];
}

export interface ProductPage {
  products: ProductCardDTO[];
  total: number;
  page: number;
  totalPages: number;
}

const cardInclude = {
  images: { orderBy: { position: "asc" }, take: 2, select: { url: true, alt: true } },
  variants: { select: { colorName: true, colorHex: true, stock: true } },
} satisfies Prisma.ProductInclude;

type CardRow = Prisma.ProductGetPayload<{ include: typeof cardInclude }>;

function toCard(row: CardRow): ProductCardDTO {
  const colors = new Map<string, string>();
  for (const variant of row.variants) colors.set(variant.colorName, variant.colorHex);
  return {
    id: row.id,
    slug: row.slug,
    name: row.name,
    price: toMoneyString(row.price),
    category: row.category,
    productType: row.productType,
    isBestseller: row.isBestseller,
    inStock: row.variants.some((variant) => variant.stock > 0),
    images: row.images,
    colors: [...colors].map(([name, hex]) => ({ name, hex })),
  };
}

/** Escapes LIKE wildcards: Prisma's `contains` passes `%` and `_` through. */
export function escapeLike(value: string): string {
  return value.replace(/[\\%_]/g, "\\$&");
}

export function buildProductWhere(filters: ShopFilters): Prisma.ProductWhereInput {
  const where: Prisma.ProductWhereInput = { isArchived: false };
  if (filters.category.length > 0) where.category = { in: filters.category };
  if (filters.type.length > 0) where.productType = { in: filters.type };
  if (filters.minPrice !== undefined || filters.maxPrice !== undefined) {
    where.price = {
      ...(filters.minPrice !== undefined ? { gte: filters.minPrice } : {}),
      ...(filters.maxPrice !== undefined ? { lte: filters.maxPrice } : {}),
    };
  }
  if (filters.size.length > 0 || filters.inStock) {
    // "Size M, in stock" means one variant that is both size M and in stock.
    where.variants = {
      some: {
        ...(filters.size.length > 0 ? { size: { in: filters.size } } : {}),
        ...(filters.inStock ? { stock: { gt: 0 } } : {}),
      },
    };
  }
  if (filters.q) {
    const term = escapeLike(filters.q);
    where.OR = [
      { name: { contains: term, mode: "insensitive" } },
      { description: { contains: term, mode: "insensitive" } },
    ];
  }
  return where;
}

function orderByFor(sort: ShopFilters["sort"]): Prisma.ProductOrderByWithRelationInput[] {
  switch (sort) {
    case "price-asc":
      return [{ price: "asc" }, { id: "asc" }];
    case "price-desc":
      return [{ price: "desc" }, { id: "asc" }];
    case "newest":
      return [{ createdAt: "desc" }, { id: "asc" }];
  }
}

// ─── Queries ────────────────────────────────────────────────────────────────

export async function searchProducts(filters: ShopFilters): Promise<ProductPage> {
  "use cache";
  cacheLife("hours");
  cacheTag(CACHE_TAGS.products);

  const where = buildProductWhere(filters);
  const total = await prisma.product.count({ where });
  const totalPages = Math.max(1, Math.ceil(total / CATALOG.pageSize));
  const page = Math.min(filters.page, totalPages);
  const rows = await prisma.product.findMany({
    where,
    include: cardInclude,
    orderBy: orderByFor(filters.sort),
    skip: (page - 1) * CATALOG.pageSize,
    take: CATALOG.pageSize,
  });
  return { products: rows.map(toCard), total, page, totalPages };
}

async function listProducts(
  where: Prisma.ProductWhereInput,
  take: number,
): Promise<ProductCardDTO[]> {
  const rows = await prisma.product.findMany({
    where: { ...where, isArchived: false },
    include: cardInclude,
    orderBy: [{ createdAt: "desc" }, { id: "asc" }],
    take,
  });
  return rows.map(toCard);
}

export async function getFeaturedProducts(take = 4): Promise<ProductCardDTO[]> {
  "use cache";
  cacheLife("hours");
  cacheTag(CACHE_TAGS.products);
  return listProducts({ isFeatured: true }, take);
}

export async function getBestsellers(take = 4): Promise<ProductCardDTO[]> {
  "use cache";
  cacheLife("hours");
  cacheTag(CACHE_TAGS.products);
  return listProducts({ isBestseller: true }, take);
}

export async function getProductBySlug(slug: string): Promise<ProductDetailDTO | null> {
  "use cache";
  cacheLife("hours");
  cacheTag(CACHE_TAGS.products, CACHE_TAGS.product(slug));

  const row = await prisma.product.findUnique({
    where: { slug },
    include: {
      images: { orderBy: { position: "asc" }, select: { url: true, alt: true } },
      variants: {
        select: { id: true, size: true, colorName: true, colorHex: true, stock: true },
        orderBy: [{ colorName: "asc" }, { size: "asc" }],
      },
    },
  });
  if (!row || row.isArchived) return null;
  const card = toCard({ ...row, images: row.images.slice(0, 2) });
  return {
    ...card,
    images: row.images,
    description: row.description,
    updatedAt: row.updatedAt.toISOString(),
    variants: row.variants,
  };
}

/**
 * Same category first, preferring the same product type. Takes only stable primitives: they are
 * the cache key, and passing the product itself would change the key whenever its stock does.
 */
export async function getRelatedProducts(
  productId: string,
  category: Category,
  productType: ProductType,
  take = 4,
): Promise<ProductCardDTO[]> {
  "use cache";
  cacheLife("hours");
  cacheTag(CACHE_TAGS.products);

  const sameType = await listProducts({ id: { not: productId }, category, productType }, take);
  if (sameType.length >= take) return sameType;
  const others = await listProducts(
    { id: { notIn: [productId, ...sameType.map((p) => p.id)] }, category },
    take - sameType.length,
  );
  return [...sameType, ...others];
}

export async function getSitemapProducts(): Promise<{ slug: string; updatedAt: Date }[]> {
  "use cache";
  cacheLife("hours");
  cacheTag(CACHE_TAGS.products);
  return prisma.product.findMany({
    where: { isArchived: false },
    select: { slug: true, updatedAt: true },
    orderBy: { createdAt: "desc" },
  });
}
