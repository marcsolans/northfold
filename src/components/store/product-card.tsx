import Image from "next/image";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";
import type { ProductCardDTO } from "@/server/queries/catalog";

const MAX_SWATCHES = 4;

export function ProductCard({
  product,
  priority = false,
  sizes = "(min-width: 1280px) 22vw, (min-width: 1024px) 30vw, 50vw",
}: {
  product: ProductCardDTO;
  /** Above-the-fold card: load its image eagerly and first (it is likely the LCP element). */
  priority?: boolean;
  sizes?: string;
}) {
  const [primary, secondary] = product.images;
  const extraColors = product.colors.length - MAX_SWATCHES;

  return (
    <article className="group relative flex flex-col">
      <div className="relative aspect-[4/5] overflow-hidden rounded-md bg-surface">
        {primary ? (
          <Image
            src={primary.url}
            alt={primary.alt}
            fill
            sizes={sizes}
            loading={priority ? "eager" : undefined}
            fetchPriority={priority ? "high" : undefined}
            className={cn(
              "object-cover transition-all duration-700 ease-out group-hover:scale-[1.03]",
              secondary && "group-hover:opacity-0",
            )}
          />
        ) : null}
        {secondary ? (
          // Hover swap only: not displayed (so, being lazy, never downloaded) on touch screens.
          <Image
            src={secondary.url}
            alt=""
            fill
            sizes={sizes}
            className="hidden object-cover opacity-0 transition-opacity duration-700 ease-out group-hover:opacity-100 [@media(hover:hover)]:block"
          />
        ) : null}
        <div className="absolute top-3 left-3 flex flex-col items-start gap-1.5">
          {!product.inStock ? <Badge tone="neutral">Sold out</Badge> : null}
          {product.inStock && product.isBestseller ? <Badge tone="accent">Bestseller</Badge> : null}
        </div>
      </div>
      <div className="mt-3 flex items-start justify-between gap-3">
        <h3 className="text-sm leading-snug">
          <Link href={`/products/${product.slug}`} className="after:absolute after:inset-0">
            {product.name}
          </Link>
        </h3>
        <p className="shrink-0 text-sm font-medium">{formatMoney(product.price)}</p>
      </div>
      {product.colors.length > 0 ? (
        <div
          className="mt-2 flex items-center gap-1.5"
          aria-label={`${product.colors.length} colours`}
        >
          {product.colors.slice(0, MAX_SWATCHES).map((color) => (
            <span
              key={color.name}
              title={color.name}
              className="size-3 rounded-full border border-foreground/15"
              style={{ backgroundColor: color.hex }}
            />
          ))}
          {extraColors > 0 ? (
            <span className="text-xs text-muted-foreground">+{extraColors}</span>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

const GRID_COLUMNS = {
  /** Full-width sections. */
  wide: "grid-cols-2 lg:grid-cols-3 xl:grid-cols-4",
  /** Next to the shop's filter sidebar. */
  sidebar: "grid-cols-2 lg:grid-cols-3",
} as const;

type GridLayout = keyof typeof GRID_COLUMNS;

export function ProductGrid({
  products,
  priorityFirst = 0,
  layout = "wide",
}: {
  products: ProductCardDTO[];
  priorityFirst?: number;
  layout?: GridLayout;
}) {
  return (
    <ul className={cn("grid gap-x-4 gap-y-10 sm:gap-x-6", GRID_COLUMNS[layout])}>
      {products.map((product, index) => (
        <li key={product.id}>
          <ProductCard product={product} priority={index < priorityFirst} />
        </li>
      ))}
    </ul>
  );
}

export function ProductGridSkeleton({
  count = 8,
  layout = "wide",
  className,
}: {
  count?: number;
  layout?: GridLayout;
  className?: string;
}) {
  return (
    <ul
      aria-hidden="true"
      className={cn("grid gap-x-4 gap-y-10 sm:gap-x-6", GRID_COLUMNS[layout], className)}
    >
      {Array.from({ length: count }, (_, index) => (
        <li key={index}>
          <div className="aspect-[4/5] animate-pulse rounded-md bg-surface" />
          <div className="mt-3 h-4 w-3/4 animate-pulse rounded bg-surface" />
          <div className="mt-2 h-3 w-1/3 animate-pulse rounded bg-surface" />
        </li>
      ))}
    </ul>
  );
}
