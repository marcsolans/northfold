import type { Metadata } from "next";
import Form from "next/form";
import Image from "next/image";
import Link from "next/link";
import { Suspense } from "react";
import { HiOutlineCube, HiPlus } from "react-icons/hi2";

import { AdminPageHeader } from "@/components/admin/admin-shell";
import { Badge } from "@/components/ui/badge";
import { buttonClasses } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Pagination } from "@/components/ui/pagination";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@/components/ui/table";
import { formatMoney } from "@/lib/money";
import { CATEGORY_LABELS, PRODUCT_TYPE_LABELS } from "@/lib/navigation";
import { cn } from "@/lib/utils";
import { firstParam, pageSchema } from "@/lib/validators/common";
import { listAdminProducts, type ProductStatusFilter } from "@/server/queries/admin";

export const metadata: Metadata = { title: "Products" };

const STATUS_TABS: { value: ProductStatusFilter; label: string }[] = [
  { value: "active", label: "Active" },
  { value: "archived", label: "Archived" },
  { value: "all", label: "All" },
];

function hrefFor(state: { q?: string; status: ProductStatusFilter; page?: number }) {
  const params = new URLSearchParams();
  if (state.q) params.set("q", state.q);
  if (state.status !== "active") params.set("status", state.status);
  if (state.page && state.page > 1) params.set("page", String(state.page));
  const query = params.toString();
  return query ? `/admin/products?${query}` : "/admin/products";
}

async function Products({ searchParams }: Pick<PageProps<"/admin/products">, "searchParams">) {
  const params = await searchParams;
  const q = firstParam(params.q)?.trim().slice(0, 100) || undefined;
  const requested = firstParam(params.status);
  const status: ProductStatusFilter =
    requested === "archived" || requested === "all" ? requested : "active";
  const page = pageSchema.parse(firstParam(params.page));
  const result = await listAdminProducts({ q, status, page });

  return (
    <>
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <nav aria-label="Product status" className="flex gap-1 rounded-md bg-surface p-1">
          {STATUS_TABS.map((tab) => (
            <Link
              key={tab.value}
              href={hrefFor({ q, status: tab.value })}
              aria-current={tab.value === status ? "page" : undefined}
              className={cn(
                "rounded px-3 py-1.5 text-sm",
                tab.value === status
                  ? "bg-card font-medium shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {tab.label}
            </Link>
          ))}
        </nav>
        <Form action="/admin/products" className="flex gap-2" role="search">
          {status !== "active" ? <input type="hidden" name="status" value={status} /> : null}
          <label htmlFor="product-search" className="sr-only">
            Search products
          </label>
          <Input
            id="product-search"
            name="q"
            defaultValue={q}
            placeholder="Name, slug or SKU"
            className="h-10 w-64"
          />
          <button
            type="submit"
            className={buttonClasses({ variant: "outline", size: "sm", className: "h-10" })}
          >
            Search
          </button>
        </Form>
      </div>

      {result.total === 0 ? (
        <EmptyState
          icon={<HiOutlineCube />}
          title="No products found"
          description="Try another search or status."
        />
      ) : (
        <>
          <Table>
            <TableHead>
              <tr>
                <TableHeaderCell>Product</TableHeaderCell>
                <TableHeaderCell>Category</TableHeaderCell>
                <TableHeaderCell className="text-right">Price</TableHeaderCell>
                <TableHeaderCell className="text-right">Stock</TableHeaderCell>
                <TableHeaderCell>Status</TableHeaderCell>
              </tr>
            </TableHead>
            <TableBody>
              {result.products.map((product) => (
                <TableRow key={product.id}>
                  <TableCell>
                    <div className="flex items-center gap-3">
                      <span className="relative size-12 shrink-0 overflow-hidden rounded bg-surface">
                        {product.imageUrl ? (
                          <Image
                            src={product.imageUrl}
                            alt=""
                            fill
                            sizes="48px"
                            className="object-cover"
                          />
                        ) : null}
                      </span>
                      <div>
                        <Link
                          href={`/admin/products/${product.id}/edit`}
                          className="font-medium hover:underline"
                        >
                          {product.name}
                        </Link>
                        <p className="text-xs text-muted-foreground">/{product.slug}</p>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {CATEGORY_LABELS[product.category]} · {PRODUCT_TYPE_LABELS[product.productType]}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatMoney(product.price)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {product.totalStock}
                    <span className="block text-xs text-muted-foreground">
                      {product.variantCount} variants
                    </span>
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {product.isArchived ? (
                        <Badge>Archived</Badge>
                      ) : (
                        <Badge tone="success">Active</Badge>
                      )}
                      {product.isFeatured ? <Badge tone="accent">Featured</Badge> : null}
                      {product.isBestseller ? <Badge tone="outline">Bestseller</Badge> : null}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <Pagination
            className="mt-8"
            page={result.page}
            totalPages={result.totalPages}
            hrefForPage={(p) => hrefFor({ q, status, page: p })}
          />
        </>
      )}
    </>
  );
}

export default function AdminProductsPage({ searchParams }: PageProps<"/admin/products">) {
  return (
    <>
      <AdminPageHeader
        title="Products"
        description="Create, edit and archive products and their variants."
        actions={
          <Link href="/admin/products/new" className={buttonClasses({ size: "sm" })}>
            <HiPlus aria-hidden="true" className="size-4" />
            New product
          </Link>
        }
      />
      <Suspense fallback={<Skeleton className="h-96 w-full" />}>
        <Products searchParams={searchParams} />
      </Suspense>
    </>
  );
}
