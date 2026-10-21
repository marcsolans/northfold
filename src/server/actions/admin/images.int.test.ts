import { beforeEach, describe, expect, it, vi } from "vitest";

import type * as EnvModule from "@/env";

import { signInAs } from "../../../../tests/auth";
import { prisma, resetDatabase } from "../../../../tests/db";
import { createProduct } from "../../../../tests/factories";

const mocks = vi.hoisted(() => ({
  features: { googleAuth: false, stripe: false, cloudinary: true },
  upload: vi.fn(),
  destroy: vi.fn(),
}));

vi.mock("@/env", async (importOriginal) => ({
  ...(await importOriginal<typeof EnvModule>()),
  features: mocks.features,
}));
vi.mock("@/lib/cloudinary", () => ({
  CLOUDINARY_FOLDER: "northfold/products",
  uploadProductImage: mocks.upload,
  destroyImages: mocks.destroy,
}));

const { discardUploadedImage, uploadProductImage } = await import("./products");

const PNG_BYTES = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 13]);

function formWith(file?: File): FormData {
  const data = new FormData();
  if (file) data.set("file", file);
  return data;
}

beforeEach(async () => {
  await resetDatabase();
  mocks.features.cloudinary = true;
  mocks.upload.mockReset();
  mocks.destroy.mockReset();
  await signInAs("ADMIN");
});

describe("uploadProductImage", () => {
  it("uploads a real image and returns its URL and public id", async () => {
    mocks.upload.mockResolvedValue({
      secure_url: "https://res.cloudinary.com/demo/image/upload/northfold/products/abc.png",
      public_id: "northfold/products/abc",
    });
    const result = await uploadProductImage(
      formWith(new File([PNG_BYTES], "shirt.png", { type: "image/png" })),
    );
    expect(result).toEqual({
      ok: true,
      data: {
        url: "https://res.cloudinary.com/demo/image/upload/northfold/products/abc.png",
        publicId: "northfold/products/abc",
      },
    });
  });

  it("rejects files whose content is not the declared image type", async () => {
    const fake = new File(["<script>alert(1)</script>"], "shirt.png", { type: "image/png" });
    await expect(uploadProductImage(formWith(fake))).resolves.toEqual({
      ok: false,
      error: "The file content does not match its image type.",
    });
    await expect(uploadProductImage(formWith())).resolves.toMatchObject({ ok: false });
    expect(mocks.upload).not.toHaveBeenCalled();
  });

  it("hides Cloudinary errors behind a generic message", async () => {
    mocks.upload.mockRejectedValue(new Error("Invalid API key abc123"));
    const result = await uploadProductImage(
      formWith(new File([PNG_BYTES], "shirt.png", { type: "image/png" })),
    );
    expect(result).toEqual({
      ok: false,
      error: "The image could not be uploaded. Please try again.",
    });
  });

  it("explains that uploads are off when Cloudinary is not configured", async () => {
    mocks.features.cloudinary = false;
    const result = await uploadProductImage(
      formWith(new File([PNG_BYTES], "shirt.png", { type: "image/png" })),
    );
    expect(result).toMatchObject({ ok: false, error: expect.stringContaining("not configured") });
  });
});

describe("discardUploadedImage", () => {
  it("deletes unsaved uploads from the products folder only", async () => {
    await expect(discardUploadedImage("northfold/products/unsaved")).resolves.toEqual({
      ok: true,
      data: undefined,
    });
    expect(mocks.destroy).toHaveBeenCalledWith(["northfold/products/unsaved"]);

    await expect(discardUploadedImage("someone-else/asset")).resolves.toMatchObject({ ok: false });
    await expect(discardUploadedImage(42)).resolves.toMatchObject({ ok: false });
    expect(mocks.destroy).toHaveBeenCalledTimes(1);
  });

  it("keeps images that a product still uses", async () => {
    const product = await createProduct();
    await prisma.productImage.updateMany({
      where: { productId: product.id },
      data: { publicId: "northfold/products/in-use" },
    });
    await expect(discardUploadedImage("northfold/products/in-use")).resolves.toMatchObject({
      ok: true,
    });
    expect(mocks.destroy).not.toHaveBeenCalled();
  });
});
