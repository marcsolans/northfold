"use client";

import Image from "next/image";
import { type ChangeEvent, useRef, useState } from "react";
import { type Control, type UseFormRegister, useFieldArray, useFormState } from "react-hook-form";
import toast from "react-hot-toast";
import { HiArrowDown, HiArrowUp, HiOutlinePhoto, HiXMark } from "react-icons/hi2";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { ALLOWED_IMAGE_TYPES, isAllowedImageUrl, MAX_IMAGE_BYTES } from "@/lib/image-validation";
import { MAX_PRODUCT_IMAGES, type ProductFormInput } from "@/lib/validators/product";
import { discardUploadedImage, uploadProductImage } from "@/server/actions/admin/products";

/**
 * Product images: upload (signed, server-side), add by URL, edit alt text, reorder, remove.
 * The first image is the cover. Removing an image uploaded in this session deletes the asset.
 */
export function ImageManager({
  control,
  register,
  defaultAlt,
  savedPublicIds,
  uploadsEnabled,
}: {
  control: Control<ProductFormInput>;
  register: UseFormRegister<ProductFormInput>;
  defaultAlt: string;
  savedPublicIds: ReadonlySet<string>;
  uploadsEnabled: boolean;
}) {
  const { fields, append, remove, move } = useFieldArray({ control, name: "images" });
  const { errors } = useFormState({ control, name: "images" });
  const [uploading, setUploading] = useState(0);
  const [urlDraft, setUrlDraft] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const remaining = MAX_PRODUCT_IMAGES - fields.length - uploading;

  async function onFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = [...(event.target.files ?? [])];
    event.target.value = "";
    if (files.length > remaining)
      toast.error(`You can add ${remaining} more image${remaining === 1 ? "" : "s"}.`);
    for (const file of files.slice(0, Math.max(0, remaining))) {
      if (!(ALLOWED_IMAGE_TYPES as readonly string[]).includes(file.type)) {
        toast.error(`${file.name}: use a JPEG, PNG, WebP or AVIF image.`);
        continue;
      }
      if (file.size > MAX_IMAGE_BYTES) {
        toast.error(`${file.name} is larger than 5 MB.`);
        continue;
      }
      setUploading((count) => count + 1);
      const body = new FormData();
      body.set("file", file);
      const result = await uploadProductImage(body).catch(() => null);
      setUploading((count) => count - 1);
      if (!result?.ok) {
        toast.error(result?.error ?? `${file.name} could not be uploaded.`);
        continue;
      }
      append({ url: result.data.url, publicId: result.data.publicId, alt: defaultAlt });
    }
  }

  function addUrl() {
    const url = urlDraft.trim();
    if (!isAllowedImageUrl(url)) {
      toast.error("Use an https image URL from Cloudinary or Unsplash.");
      return;
    }
    append({ url, publicId: null, alt: defaultAlt });
    setUrlDraft("");
  }

  function removeAt(index: number, publicId: string | null | undefined) {
    remove(index);
    if (publicId && !savedPublicIds.has(publicId)) void discardUploadedImage(publicId);
  }

  const arrayError = errors.images?.message ?? errors.images?.root?.message;

  return (
    <div className="space-y-4">
      {fields.length > 0 ? (
        <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3">
          {fields.map((field, index) => (
            <li key={field.id} className="rounded-lg border border-border bg-card p-2">
              <div className="relative aspect-[4/5] overflow-hidden rounded bg-surface">
                <Image src={field.url} alt="" fill sizes="200px" className="object-cover" />
                {index === 0 ? (
                  <span className="absolute top-2 left-2 rounded bg-primary px-2 py-0.5 text-[0.65rem] font-medium text-primary-foreground">
                    Cover
                  </span>
                ) : null}
              </div>
              <label className="sr-only" htmlFor={`image-alt-${field.id}`}>
                Alt text for image {index + 1}
              </label>
              <Input
                id={`image-alt-${field.id}`}
                placeholder="Alt text"
                className="mt-2 h-9 text-xs"
                aria-invalid={errors.images?.[index]?.alt ? true : undefined}
                {...register(`images.${index}.alt`)}
              />
              <div className="mt-2 flex justify-between">
                <div className="flex gap-1">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-8"
                    aria-label={`Move image ${index + 1} earlier`}
                    disabled={index === 0}
                    onClick={() => move(index, index - 1)}
                  >
                    <HiArrowUp aria-hidden="true" className="size-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-8"
                    aria-label={`Move image ${index + 1} later`}
                    disabled={index === fields.length - 1}
                    onClick={() => move(index, index + 1)}
                  >
                    <HiArrowDown aria-hidden="true" className="size-4" />
                  </Button>
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-8 text-destructive"
                  aria-label={`Remove image ${index + 1}`}
                  onClick={() => removeAt(index, field.publicId)}
                >
                  <HiXMark aria-hidden="true" className="size-4" />
                </Button>
              </div>
            </li>
          ))}
          {Array.from({ length: uploading }, (_, i) => (
            <li
              key={`uploading-${i}`}
              className="flex aspect-[4/5] items-center justify-center rounded-lg border border-dashed border-border"
            >
              <Spinner label="Uploading image" />
            </li>
          ))}
        </ul>
      ) : (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border py-10 text-sm text-muted-foreground">
          <HiOutlinePhoto aria-hidden="true" className="size-8" />
          No images yet — add at least one.
        </div>
      )}

      {arrayError ? (
        <p role="alert" className="text-xs text-destructive">
          {arrayError}
        </p>
      ) : null}

      <div className="flex flex-col gap-3 sm:flex-row">
        <input
          ref={fileInput}
          type="file"
          accept={ALLOWED_IMAGE_TYPES.join(",")}
          multiple
          className="sr-only"
          tabIndex={-1}
          aria-hidden="true"
          onChange={(event) => void onFiles(event)}
        />
        <Button
          variant="outline"
          disabled={!uploadsEnabled || remaining <= 0}
          loading={uploading > 0}
          onClick={() => fileInput.current?.click()}
        >
          Upload images
        </Button>
        <div className="flex flex-1 gap-2">
          <label htmlFor="image-url" className="sr-only">
            Image URL
          </label>
          <Input
            id="image-url"
            value={urlDraft}
            onChange={(event) => setUrlDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                addUrl();
              }
            }}
            placeholder="…or paste an https image URL"
            disabled={remaining <= 0}
          />
          <Button
            variant="secondary"
            onClick={addUrl}
            disabled={remaining <= 0 || urlDraft.trim() === ""}
          >
            Add
          </Button>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        Up to {MAX_PRODUCT_IMAGES} images · JPEG, PNG, WebP or AVIF · 5 MB each.
        {uploadsEnabled ? "" : " Uploads are disabled because Cloudinary is not configured."}
      </p>
    </div>
  );
}
