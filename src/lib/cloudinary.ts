import "server-only";

import { type UploadApiResponse, v2 as cloudinary } from "cloudinary";

import { env, features } from "@/env";

import { logger } from "./logger";

export const CLOUDINARY_FOLDER = "northfold/products";

let configured = false;

function client() {
  if (!features.cloudinary) throw new Error("Cloudinary is not configured");
  if (!configured) {
    cloudinary.config({
      cloud_name: env.CLOUDINARY_CLOUD_NAME,
      api_key: env.CLOUDINARY_API_KEY,
      api_secret: env.CLOUDINARY_API_SECRET,
      secure: true,
    });
    configured = true;
  }
  return cloudinary;
}

/** Signed server-side upload (the API secret never leaves the server). */
export function uploadProductImage(bytes: Buffer): Promise<UploadApiResponse> {
  return new Promise((resolve, reject) => {
    client()
      .uploader.upload_stream(
        {
          resource_type: "image",
          folder: CLOUDINARY_FOLDER,
          asset_folder: CLOUDINARY_FOLDER,
          allowed_formats: ["jpg", "jpeg", "png", "webp", "avif"],
          overwrite: false,
          unique_filename: true,
        },
        (error, result) => {
          if (error || !result) reject(error ?? new Error("Cloudinary returned no result"));
          else resolve(result);
        },
      )
      .end(bytes);
  });
}

/** Deletes assets; failures are logged, not thrown (an orphaned asset is not worth failing a save). */
export async function destroyImages(publicIds: readonly string[]): Promise<void> {
  if (publicIds.length === 0 || !features.cloudinary) return;
  await Promise.all(
    publicIds.map(async (publicId) => {
      try {
        await client().uploader.destroy(publicId, { resource_type: "image", invalidate: true });
      } catch (error) {
        logger.warn("Could not delete Cloudinary image", { publicId, error });
      }
    }),
  );
}
