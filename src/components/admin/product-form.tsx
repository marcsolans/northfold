"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import toast from "react-hot-toast";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Field } from "@/components/ui/field";
import { Input, Textarea } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Category, ProductType } from "@/generated/prisma/enums";
import { CATEGORY_LABELS, PRODUCT_TYPE_LABELS } from "@/lib/navigation";
import { slugify } from "@/lib/utils";
import {
  type ProductFormData,
  type ProductFormInput,
  productFormSchema,
} from "@/lib/validators/product";
import { createProduct, updateProduct } from "@/server/actions/admin/products";
import type { AdminProductDetail } from "@/server/queries/admin";

import { ImageManager } from "./image-manager";
import { VariantsEditor } from "./variants-editor";

const EMPTY: ProductFormInput = {
  name: "",
  slug: "",
  description: "",
  price: "",
  category: "MEN",
  productType: "TSHIRT",
  isFeatured: false,
  isBestseller: false,
  isArchived: false,
  images: [],
  variants: [{ size: "M", colorName: "", colorHex: "#1f1f1d", sku: "", stock: 0 }],
};

function defaultsFrom(product: AdminProductDetail | null): ProductFormInput {
  if (!product) return EMPTY;
  return {
    name: product.name,
    slug: product.slug,
    description: product.description,
    price: product.price,
    category: product.category,
    productType: product.productType,
    isFeatured: product.isFeatured,
    isBestseller: product.isBestseller,
    isArchived: product.isArchived,
    images: product.images,
    variants: product.variants.map(({ id, size, colorName, colorHex, sku, stock }) => ({
      id,
      size,
      colorName,
      colorHex,
      sku,
      stock,
    })),
  };
}

export function ProductForm({
  product,
  uploadsEnabled,
}: {
  product: AdminProductDetail | null;
  uploadsEnabled: boolean;
}) {
  const router = useRouter();
  const [slugEdited, setSlugEdited] = useState(Boolean(product));
  const form = useForm<ProductFormInput, unknown, ProductFormData>({
    resolver: zodResolver(productFormSchema),
    defaultValues: defaultsFrom(product),
  });
  const { register, control, formState, setValue, getValues, setError } = form;
  const { errors, isSubmitting, isDirty } = formState;
  const name = useWatch({ control, name: "name" });
  const slug = useWatch({ control, name: "slug" });

  const savedPublicIds = useMemo(
    () =>
      new Set(product?.images.flatMap((image) => (image.publicId ? [image.publicId] : [])) ?? []),
    [product],
  );
  const lockedVariantIds = useMemo(
    () =>
      new Set(
        product?.variants.filter((variant) => variant.hasOrders).map((variant) => variant.id) ?? [],
      ),
    [product],
  );

  const nameField = register("name", {
    onChange: (event: { target: { value: string } }) => {
      if (!slugEdited) setValue("slug", slugify(event.target.value), { shouldValidate: false });
    },
  });

  const onSubmit = form.handleSubmit(async (values) => {
    const result = product ? await updateProduct(product.id, values) : await createProduct(values);
    if (!result.ok) {
      const slugError = result.fieldErrors?.slug?.[0];
      if (slugError) setError("slug", { type: "server", message: slugError });
      const variantsError = result.fieldErrors?.variants?.[0];
      if (variantsError) setError("variants", { type: "server", message: variantsError });
      toast.error(result.error);
      return;
    }
    toast.success(product ? "Product saved" : "Product created");
    if (product) {
      form.reset(values);
      router.refresh();
    } else {
      // The "new" route stays mounted (hidden) after navigation; start blank next time.
      form.reset(EMPTY);
      setSlugEdited(false);
      router.push(`/admin/products/${result.data.id}/edit`);
    }
  });

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Details</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-5 sm:grid-cols-2">
          <Field label="Name" error={errors.name?.message} className="sm:col-span-2">
            {(field) => <Input {...field} {...nameField} />}
          </Field>
          <Field
            label="URL slug"
            hint={`/products/${slug || "…"}`}
            error={errors.slug?.message}
            className="sm:col-span-2"
          >
            {(field) => (
              <Input
                {...field}
                {...register("slug", { onChange: () => setSlugEdited(true) })}
                spellCheck={false}
              />
            )}
          </Field>
          <Field label="Description" error={errors.description?.message} className="sm:col-span-2">
            {(field) => <Textarea {...field} rows={5} {...register("description")} />}
          </Field>
          <Field label="Price (USD)" error={errors.price?.message}>
            {(field) => (
              <Input {...field} inputMode="decimal" placeholder="49.00" {...register("price")} />
            )}
          </Field>
          <div />
          <Field label="Category" error={errors.category?.message}>
            {(field) => (
              <Select
                {...field}
                options={Object.values(Category).map((value) => ({
                  value,
                  label: CATEGORY_LABELS[value],
                }))}
                {...register("category")}
              />
            )}
          </Field>
          <Field label="Product type" error={errors.productType?.message}>
            {(field) => (
              <Select
                {...field}
                options={Object.values(ProductType).map((value) => ({
                  value,
                  label: PRODUCT_TYPE_LABELS[value],
                }))}
                {...register("productType")}
              />
            )}
          </Field>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Visibility</CardTitle>
          <CardDescription>
            Archived products are hidden from the store but kept for order history.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-3">
          <Checkbox label="Featured on the home page" {...register("isFeatured")} />
          <Checkbox label="Bestseller" {...register("isBestseller")} />
          <Checkbox label="Archived" {...register("isArchived")} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Images</CardTitle>
        </CardHeader>
        <CardContent>
          <ImageManager
            control={control}
            register={register}
            defaultAlt={name}
            savedPublicIds={savedPublicIds}
            uploadsEnabled={uploadsEnabled}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Variants</CardTitle>
          <CardDescription>
            One row per size and colour, each with its own SKU and stock.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <VariantsEditor
            control={control}
            register={register}
            getValues={getValues}
            setValue={setValue}
            lockedVariantIds={lockedVariantIds}
          />
        </CardContent>
      </Card>

      <div className="sticky bottom-0 -mx-4 flex justify-end gap-3 border-t border-border bg-background/95 px-4 py-4 backdrop-blur sm:mx-0 sm:rounded-lg sm:border">
        <Button
          variant="ghost"
          onClick={() => router.push("/admin/products")}
          disabled={isSubmitting}
        >
          Cancel
        </Button>
        <Button
          type="submit"
          loading={isSubmitting}
          loadingText="Saving…"
          disabled={Boolean(product) && !isDirty}
        >
          {product ? "Save changes" : "Create product"}
        </Button>
      </div>
    </form>
  );
}
