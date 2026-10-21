import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { HiOutlineMagnifyingGlass } from "react-icons/hi2";

import { ActiveFilters, countActiveFilters } from "@/components/store/active-filters";
import { MobileFilters } from "@/components/store/mobile-filters";
import { ProductGrid, ProductGridSkeleton } from "@/components/store/product-card";
import { ShopFilters } from "@/components/store/shop-filters";
import { SortSelect } from "@/components/store/sort-select";
import { buttonClasses } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Pagination } from "@/components/ui/pagination";
import { Skeleton } from "@/components/ui/skeleton";
import { CATEGORY_LABELS } from "@/lib/navigation";
import { shopHref } from "@/lib/shop-url";
import { pluralize } from "@/lib/utils";
import { parseShopFilters, type ShopFilters as Filters } from "@/lib/validators/catalog";
import { searchProducts } from "@/server/queries/catalog";

function titleFor(filters: Filters): string {
  if (filters.q) return `Results for “${filters.q}”`;
  const [only] = filters.category;
  if (filters.category.length === 1 && only) return CATEGORY_LABELS[only];
  return "All products";
}

export async function generateMetadata({ searchParams }: PageProps<"/shop">): Promise<Metadata> {
  const filters = parseShopFilters(await searchParams);
  const title = titleFor(filters);
  return {
    title: title === "All products" ? "Shop" : title,
    description: "Browse Northfold's minimal, well-made clothing for men, women and children.",
    alternates: { canonical: shopHref({ category: filters.category }) },
  };
}

async function ShopResults({ filters }: { filters: Filters }) {
  const result = await searchProducts(filters);

  if (result.total === 0) {
    return (
      <EmptyState
        icon={<HiOutlineMagnifyingGlass />}
        title="No products match"
        description="Try removing a filter or searching for something else."
        action={
          <Link href="/shop" className={buttonClasses({ variant: "outline" })}>
            Clear all filters
          </Link>
        }
      />
    );
  }

  return (
    <>
      <p className="mb-6 text-sm text-muted-foreground" aria-live="polite">
        {pluralize(result.total, "product")}
      </p>
      <ProductGrid products={result.products} priorityFirst={2} layout="sidebar" />
      <Pagination
        className="mt-14"
        page={result.page}
        totalPages={result.totalPages}
        hrefForPage={(page) => shopHref({ ...filters, page })}
      />
    </>
  );
}

async function ShopContent({ searchParams }: Pick<PageProps<"/shop">, "searchParams">) {
  const filters = parseShopFilters(await searchParams);
  const stateKey = shopHref(filters);

  return (
    <>
      <div className="flex flex-col gap-2 border-b border-border pb-6">
        <p className="text-xs font-medium tracking-[0.25em] text-accent uppercase">Shop</p>
        <h1 className="text-3xl font-light tracking-tight sm:text-4xl">{titleFor(filters)}</h1>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-4 py-5">
        <div className="flex flex-wrap items-center gap-3">
          <MobileFilters
            key={stateKey}
            filters={filters}
            activeCount={countActiveFilters(filters)}
          />
          <ActiveFilters filters={filters} />
        </div>
        <SortSelect filters={filters} />
      </div>
      <div className="grid gap-10 lg:grid-cols-[15rem_1fr]">
        <aside aria-label="Filters" className="hidden lg:block">
          <ShopFilters key={stateKey} filters={filters} />
        </aside>
        <section aria-labelledby="products-heading">
          <h2 id="products-heading" className="sr-only">
            Products
          </h2>
          <Suspense key={stateKey} fallback={<ProductGridSkeleton count={6} layout="sidebar" />}>
            <ShopResults filters={filters} />
          </Suspense>
        </section>
      </div>
    </>
  );
}

function ShopSkeleton() {
  return (
    <div aria-busy="true">
      <Skeleton className="h-4 w-16" />
      <Skeleton className="mt-3 h-10 w-64" />
      <div className="mt-10 grid gap-10 lg:grid-cols-[15rem_1fr]">
        <Skeleton className="hidden h-96 lg:block" />
        <ProductGridSkeleton count={6} layout="sidebar" />
      </div>
    </div>
  );
}

export default function ShopPage({ searchParams }: PageProps<"/shop">) {
  return (
    <div className="mx-auto max-w-7xl px-4 pt-10 pb-16 sm:px-6">
      <Suspense fallback={<ShopSkeleton />}>
        <ShopContent searchParams={searchParams} />
      </Suspense>
    </div>
  );
}
