import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { HiArrowTopRightOnSquare } from "react-icons/hi2";

import { AdminPageHeader } from "@/components/admin/admin-shell";
import { ProductDangerZone } from "@/components/admin/product-danger-zone";
import { ProductForm } from "@/components/admin/product-form";
import { buttonClasses } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { features } from "@/env";
import { getAdminProduct } from "@/server/queries/admin";

export const metadata: Metadata = { title: "Edit product" };

async function EditProduct({ params }: Pick<PageProps<"/admin/products/[id]/edit">, "params">) {
  const { id } = await params;
  const product = await getAdminProduct(id);
  if (!product) notFound();

  return (
    <>
      <AdminPageHeader
        title={product.name}
        description={
          product.isArchived ? "Archived — hidden from the store." : "Live in the store."
        }
        actions={
          product.isArchived ? null : (
            <Link
              href={`/products/${product.slug}`}
              target="_blank"
              className={buttonClasses({ variant: "outline", size: "sm" })}
            >
              View in store
              <HiArrowTopRightOnSquare aria-hidden="true" className="size-4" />
            </Link>
          )
        }
      />
      <div className="space-y-6">
        <ProductForm key={product.id} product={product} uploadsEnabled={features.cloudinary} />
        <ProductDangerZone productId={product.id} hasOrders={product.hasOrders} />
      </div>
    </>
  );
}

export default function EditProductPage({ params }: PageProps<"/admin/products/[id]/edit">) {
  return (
    <Suspense fallback={<Skeleton className="h-[40rem] w-full" />}>
      <EditProduct params={params} />
    </Suspense>
  );
}
