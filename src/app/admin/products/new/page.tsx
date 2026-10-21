import type { Metadata } from "next";

import { AdminPageHeader } from "@/components/admin/admin-shell";
import { ProductForm } from "@/components/admin/product-form";
import { features } from "@/env";

export const metadata: Metadata = { title: "New product" };

export default function NewProductPage() {
  return (
    <>
      <AdminPageHeader
        title="New product"
        description="Add details, images and at least one variant."
      />
      <ProductForm product={null} uploadsEnabled={features.cloudinary} />
    </>
  );
}
