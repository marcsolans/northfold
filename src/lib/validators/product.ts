import { z } from "zod";

import { Category, ProductType, Size } from "@/generated/prisma/enums";

import { idSchema, moneyStringSchema, requiredText } from "./common";

export const MAX_PRODUCT_IMAGES = 6;
export const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
export const ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp", "image/avif"] as const;

export const productImageSchema = z.object({
  url: z.url({ error: "Invalid image URL" }),
  publicId: z.string().trim().max(255).nullable(),
  alt: requiredText("Alt text", 160),
});
export type ProductImageInput = z.infer<typeof productImageSchema>;

export const productVariantSchema = z.object({
  id: idSchema.optional(),
  size: z.enum(Size, { error: "Choose a size" }),
  colorName: requiredText("Colour", 40),
  colorHex: z
    .string()
    .trim()
    .regex(/^#[0-9a-fA-F]{6}$/, { error: "Use a hex colour like #1f1f1d" }),
  sku: z
    .string()
    .trim()
    .toUpperCase()
    .regex(/^[A-Z0-9-]{3,40}$/, { error: "SKU: 3–40 letters, digits or dashes" }),
  stock: z.coerce
    .number({ error: "Stock must be a number" })
    .int({ error: "Stock must be a whole number" })
    .min(0, { error: "Stock cannot be negative" })
    .max(100_000),
});
export type ProductVariantInput = z.input<typeof productVariantSchema>;

export const productFormSchema = z
  .object({
    name: requiredText("Name", 120),
    slug: z
      .string()
      .trim()
      .toLowerCase()
      .regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/, { error: "Use lowercase letters, digits and dashes" })
      .max(140),
    description: requiredText("Description", 4000),
    price: moneyStringSchema.refine((value) => Number(value) > 0, {
      error: "Price must be above zero",
    }),
    category: z.enum(Category, { error: "Choose a category" }),
    productType: z.enum(ProductType, { error: "Choose a product type" }),
    isFeatured: z.boolean(),
    isBestseller: z.boolean(),
    isArchived: z.boolean(),
    images: z
      .array(productImageSchema)
      .min(1, { error: "Add at least one image" })
      .max(MAX_PRODUCT_IMAGES, { error: `At most ${MAX_PRODUCT_IMAGES} images` }),
    variants: z.array(productVariantSchema).min(1, { error: "Add at least one variant" }).max(60),
  })
  .superRefine((product, ctx) => {
    const combos = new Map<string, number>();
    const skus = new Map<string, number>();
    product.variants.forEach((variant, index) => {
      const combo = `${variant.size}|${variant.colorName.toLowerCase()}`;
      if (combos.has(combo)) {
        ctx.addIssue({
          code: "custom",
          path: ["variants", index, "colorName"],
          message: `Duplicate ${variant.size} / ${variant.colorName} variant`,
        });
      }
      combos.set(combo, index);
      if (skus.has(variant.sku)) {
        ctx.addIssue({
          code: "custom",
          path: ["variants", index, "sku"],
          message: "SKU must be unique",
        });
      }
      skus.set(variant.sku, index);
    });
  });
export type ProductFormInput = z.input<typeof productFormSchema>;
export type ProductFormData = z.output<typeof productFormSchema>;
