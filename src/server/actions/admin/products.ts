"use server";

import { revalidatePath, updateTag } from "next/cache";

import { features } from "@/env";
import { Prisma } from "@/generated/prisma/client";
import { type ActionResult, fail, ok } from "@/lib/action-result";
import { CACHE_TAGS } from "@/lib/cache-tags";
import {
  CLOUDINARY_FOLDER,
  destroyImages,
  uploadProductImage as uploadToCloudinary,
} from "@/lib/cloudinary";
import { checkImageFile } from "@/lib/image-validation";
import { logger } from "@/lib/logger";
import { prisma } from "@/lib/prisma";
import { fieldErrorsFrom, idSchema } from "@/lib/validators/common";
import { type ProductFormData, productFormSchema } from "@/lib/validators/product";
import { runAction, UserFacingError } from "@/server/action";
import { requireAdmin } from "@/server/auth/session";

// ─── Helpers ────────────────────────────────────────────────────────────────

/** Reads a nested property of an untyped object without assertions. */
function readPath(value: unknown, path: readonly string[]): unknown {
  let current: unknown = value;
  for (const key of path) {
    if (typeof current !== "object" || current === null) return undefined;
    current = Reflect.get(current, key);
  }
  return current;
}

/** Which unique index a Prisma 7 P2002 error came from (driver adapters report it here). */
function violatedConstraint(error: unknown): string | null {
  if (!(error instanceof Prisma.PrismaClientKnownRequestError) || error.code !== "P2002")
    return null;
  const index = readPath(error.meta, ["driverAdapterError", "cause", "constraint", "index"]);
  return typeof index === "string" ? index : "unknown";
}

function uniqueViolationResult(error: unknown): ActionResult<never> | null {
  const constraint = violatedConstraint(error);
  if (!constraint) return null;
  if (constraint.includes("slug")) {
    return fail("That URL slug is already used by another product.", { slug: ["Already in use"] });
  }
  if (constraint.includes("sku")) {
    return fail("One of the SKUs is already used by another product.", {
      variants: ["SKUs must be unique"],
    });
  }
  return fail("Two variants share the same size and colour.", {
    variants: ["Duplicate size/colour"],
  });
}

function productFields(data: ProductFormData) {
  return {
    name: data.name,
    slug: data.slug,
    description: data.description,
    price: data.price,
    category: data.category,
    productType: data.productType,
    isFeatured: data.isFeatured,
    isBestseller: data.isBestseller,
    isArchived: data.isArchived,
  };
}

function imageRows(productId: string, images: ProductFormData["images"]) {
  return images.map((image, position) => ({
    productId,
    url: image.url,
    publicId: image.publicId,
    alt: image.alt,
    position,
  }));
}

function refreshCatalog(...slugs: string[]) {
  updateTag(CACHE_TAGS.products);
  for (const slug of new Set(slugs)) updateTag(CACHE_TAGS.product(slug));
  revalidatePath("/admin/products");
  revalidatePath("/admin");
}

// ─── Images ─────────────────────────────────────────────────────────────────

/** Signed server-side upload of one image (max 5 MB; JPEG, PNG, WebP or AVIF, checked by content). */
export async function uploadProductImage(
  formData: FormData,
): Promise<ActionResult<{ url: string; publicId: string }>> {
  return runAction("admin.uploadProductImage", async () => {
    await requireAdmin();
    if (!features.cloudinary)
      return fail("Image uploads are not configured. Add images by URL instead.");
    const file = formData.get("file");
    if (!(file instanceof File)) return fail("Choose an image to upload.");

    const bytes = Buffer.from(await file.arrayBuffer());
    const check = checkImageFile(file.type, file.size, bytes.subarray(0, 16));
    if (!check.ok) return fail(check.error);

    try {
      const uploaded = await uploadToCloudinary(bytes);
      return ok({ url: uploaded.secure_url, publicId: uploaded.public_id });
    } catch (error) {
      logger.error("Cloudinary upload failed", { error });
      return fail("The image could not be uploaded. Please try again.");
    }
  });
}

/** Deletes an uploaded image that was removed from the form before it was ever saved. */
export async function discardUploadedImage(publicId: unknown): Promise<ActionResult> {
  return runAction("admin.discardUploadedImage", async () => {
    await requireAdmin();
    if (typeof publicId !== "string" || !publicId.startsWith(`${CLOUDINARY_FOLDER}/`)) {
      return fail("Unknown image.");
    }
    const inUse = await prisma.productImage.count({ where: { publicId } });
    if (inUse === 0) await destroyImages([publicId]);
    return ok();
  });
}

// ─── Products ───────────────────────────────────────────────────────────────

export async function createProduct(
  input: unknown,
): Promise<ActionResult<{ id: string; slug: string }>> {
  return runAction("admin.createProduct", async () => {
    await requireAdmin();
    const parsed = productFormSchema.safeParse(input);
    if (!parsed.success)
      return fail("Please fix the highlighted fields.", fieldErrorsFrom(parsed.error));
    const data = parsed.data;

    try {
      const product = await prisma.$transaction(async (tx) => {
        const created = await tx.product.create({ data: productFields(data) });
        await tx.productImage.createMany({ data: imageRows(created.id, data.images) });
        await tx.productVariant.createMany({
          data: data.variants.map((variant) => ({
            productId: created.id,
            size: variant.size,
            colorName: variant.colorName,
            colorHex: variant.colorHex,
            sku: variant.sku,
            stock: variant.stock,
          })),
        });
        return created;
      });
      refreshCatalog(product.slug);
      return ok({ id: product.id, slug: product.slug });
    } catch (error) {
      const result = uniqueViolationResult(error);
      if (result) return result;
      throw error;
    }
  });
}

export async function updateProduct(
  productId: unknown,
  input: unknown,
): Promise<ActionResult<{ id: string; slug: string }>> {
  return runAction("admin.updateProduct", async () => {
    await requireAdmin();
    const id = idSchema.safeParse(productId);
    if (!id.success) return fail("Product not found.");
    const parsed = productFormSchema.safeParse(input);
    if (!parsed.success)
      return fail("Please fix the highlighted fields.", fieldErrorsFrom(parsed.error));
    const data = parsed.data;

    const existing = await prisma.product.findUnique({
      where: { id: id.data },
      include: {
        images: { select: { publicId: true } },
        variants: { include: { _count: { select: { orderItems: true } } } },
      },
    });
    if (!existing) return fail("Product not found.");

    const existingIds = new Set(existing.variants.map((variant) => variant.id));
    if (data.variants.some((variant) => variant.id !== undefined && !existingIds.has(variant.id))) {
      return fail("A variant does not belong to this product. Refresh and try again.");
    }
    const keptIds = new Set(data.variants.flatMap((variant) => (variant.id ? [variant.id] : [])));
    const removed = existing.variants.filter((variant) => !keptIds.has(variant.id));
    const removedWithOrders = removed.filter((variant) => variant._count.orderItems > 0);
    if (removedWithOrders.length > 0) {
      return fail(
        `${removedWithOrders.map((v) => v.sku).join(", ")} ${removedWithOrders.length === 1 ? "has" : "have"} orders and cannot be removed. Set the stock to 0 instead.`,
      );
    }

    try {
      await prisma.$transaction(async (tx) => {
        await tx.product.update({ where: { id: existing.id }, data: productFields(data) });
        await tx.productImage.deleteMany({ where: { productId: existing.id } });
        await tx.productImage.createMany({ data: imageRows(existing.id, data.images) });
        if (removed.length > 0) {
          await tx.productVariant.deleteMany({
            where: { id: { in: removed.map((variant) => variant.id) } },
          });
        }
        for (const variant of data.variants) {
          const fields = {
            size: variant.size,
            colorName: variant.colorName,
            colorHex: variant.colorHex,
            sku: variant.sku,
            stock: variant.stock,
          };
          if (variant.id)
            await tx.productVariant.update({ where: { id: variant.id }, data: fields });
          else await tx.productVariant.create({ data: { ...fields, productId: existing.id } });
        }
      });
    } catch (error) {
      const result = uniqueViolationResult(error);
      if (result) return result;
      throw error;
    }

    const keptImages = new Set(data.images.map((image) => image.publicId));
    await destroyImages(
      existing.images.flatMap((image) =>
        image.publicId && !keptImages.has(image.publicId) ? [image.publicId] : [],
      ),
    );
    refreshCatalog(existing.slug, data.slug);
    return ok({ id: existing.id, slug: data.slug });
  });
}

export async function setProductArchived(
  productId: unknown,
  archived: unknown,
): Promise<ActionResult> {
  return runAction("admin.setProductArchived", async () => {
    await requireAdmin();
    const id = idSchema.safeParse(productId);
    if (!id.success || typeof archived !== "boolean") return fail("Product not found.");
    const product = await prisma.product.findUnique({
      where: { id: id.data },
      select: { slug: true },
    });
    if (!product) return fail("Product not found.");
    await prisma.product.update({ where: { id: id.data }, data: { isArchived: archived } });
    refreshCatalog(product.slug);
    return ok();
  });
}

/**
 * Hard delete, only for products that were never ordered (their images are removed from
 * Cloudinary too). Products with orders must be archived so order history stays intact.
 */
export async function deleteProduct(productId: unknown): Promise<ActionResult> {
  return runAction("admin.deleteProduct", async () => {
    await requireAdmin();
    const id = idSchema.safeParse(productId);
    if (!id.success) return fail("Product not found.");

    const product = await prisma.$transaction(async (tx) => {
      const found = await tx.product.findUnique({
        where: { id: id.data },
        include: { images: true },
      });
      if (!found) throw new UserFacingError("Product not found.");
      const ordered = await tx.orderItem.count({ where: { variant: { productId: found.id } } });
      if (ordered > 0)
        throw new UserFacingError("This product has orders, so it can only be archived.");
      await tx.product.delete({ where: { id: found.id } });
      return found;
    });

    await destroyImages(
      product.images.flatMap((image) => (image.publicId ? [image.publicId] : [])),
    );
    refreshCatalog(product.slug);
    return ok();
  });
}
