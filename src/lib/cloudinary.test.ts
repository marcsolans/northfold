import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  features: { cloudinary: true },
  config: vi.fn(),
  uploadStream: vi.fn(),
  destroy: vi.fn(),
  warn: vi.fn(),
}));

vi.mock("@/env", () => ({
  env: {
    CLOUDINARY_CLOUD_NAME: "demo",
    CLOUDINARY_API_KEY: "key",
    CLOUDINARY_API_SECRET: "secret",
  },
  features: mocks.features,
}));
vi.mock("cloudinary", () => ({
  v2: {
    config: mocks.config,
    uploader: { upload_stream: mocks.uploadStream, destroy: mocks.destroy },
  },
}));
vi.mock("./logger", () => ({ logger: { warn: mocks.warn } }));

const { CLOUDINARY_FOLDER, destroyImages, uploadProductImage } = await import("./cloudinary");

type UploadCallback = (error: unknown, result?: unknown) => void;

/** Simulates Cloudinary's stream API: the callback fires once the bytes are written. */
function respondWith(error: unknown, result?: unknown) {
  mocks.uploadStream.mockImplementation((_options: unknown, callback: UploadCallback) => ({
    end: vi.fn(() => callback(error, result)),
  }));
}

beforeEach(() => {
  mocks.features.cloudinary = true;
  vi.clearAllMocks();
});

describe("uploadProductImage", () => {
  // Runs first: the SDK is configured lazily, once per process.
  it("configures the SDK once with signed credentials", async () => {
    respondWith(undefined, { public_id: "a" });
    await uploadProductImage(Buffer.from("1"));
    await uploadProductImage(Buffer.from("2"));
    expect(mocks.config).toHaveBeenCalledTimes(1);
    expect(mocks.config).toHaveBeenCalledWith(
      expect.objectContaining({ cloud_name: "demo", api_secret: "secret", secure: true }),
    );
  });

  it("uploads into the products folder with a format allow-list", async () => {
    respondWith(undefined, { public_id: `${CLOUDINARY_FOLDER}/abc`, secure_url: "https://x" });
    await expect(uploadProductImage(Buffer.from("img"))).resolves.toMatchObject({
      public_id: `${CLOUDINARY_FOLDER}/abc`,
    });
    expect(mocks.uploadStream).toHaveBeenCalledWith(
      expect.objectContaining({
        folder: CLOUDINARY_FOLDER,
        resource_type: "image",
        allowed_formats: ["jpg", "jpeg", "png", "webp", "avif"],
        overwrite: false,
      }),
      expect.any(Function),
    );
  });

  it("rejects when Cloudinary fails or returns nothing", async () => {
    respondWith(new Error("Invalid image file"));
    await expect(uploadProductImage(Buffer.from("x"))).rejects.toThrow("Invalid image file");
    respondWith(undefined, undefined);
    await expect(uploadProductImage(Buffer.from("x"))).rejects.toThrow("no result");
  });

  it("rejects when Cloudinary is not configured", async () => {
    mocks.features.cloudinary = false;
    await expect(uploadProductImage(Buffer.from("x"))).rejects.toThrow("not configured");
    expect(mocks.uploadStream).not.toHaveBeenCalled();
  });
});

describe("destroyImages", () => {
  it("deletes every image and only logs failures", async () => {
    mocks.destroy.mockResolvedValueOnce({ result: "ok" }).mockRejectedValueOnce(new Error("boom"));
    await expect(destroyImages(["a", "b"])).resolves.toBeUndefined();
    expect(mocks.destroy).toHaveBeenCalledTimes(2);
    expect(mocks.warn).toHaveBeenCalledWith(
      "Could not delete Cloudinary image",
      expect.objectContaining({ publicId: "b" }),
    );
  });

  it("does nothing without ids or without Cloudinary", async () => {
    await destroyImages([]);
    mocks.features.cloudinary = false;
    await destroyImages(["a"]);
    expect(mocks.destroy).not.toHaveBeenCalled();
  });
});
