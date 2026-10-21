"use client";

import Image, { getImageProps } from "next/image";
import { useState } from "react";
import { preload } from "react-dom";

import { cn } from "@/lib/utils";
import type { ProductImageDTO } from "@/server/queries/catalog";

const STRIP_SIZES = "85vw";
const MAIN_SIZES = "(min-width: 1024px) 50vw, 80vw";

/**
 * The first image is the LCP element, but each layout renders it at a different size. One
 * high-priority preload per breakpoint means a phone only fetches the strip image and a desktop
 * only the main one (a plain `preload` prop would fetch both everywhere).
 */
function preloadFirstImage(url: string) {
  for (const [sizes, media] of [
    [STRIP_SIZES, "(max-width: 639.98px)"],
    [MAIN_SIZES, "(min-width: 640px)"],
  ] as const) {
    const { props } = getImageProps({ src: url, alt: "", fill: true, sizes });
    preload(props.src, {
      as: "image",
      imageSrcSet: props.srcSet,
      imageSizes: props.sizes,
      fetchPriority: "high",
      media,
    });
  }
}

/**
 * Mobile: swipeable, scroll-snapping strip. Desktop: main image with thumbnail buttons.
 */
export function ProductGallery({
  images,
  productName,
}: {
  images: ProductImageDTO[];
  productName: string;
}) {
  const [active, setActive] = useState(0);
  const current = images[active] ?? images[0];
  if (images[0]) preloadFirstImage(images[0].url);

  if (!current) {
    return (
      <div
        className="aspect-[4/5] rounded-lg bg-surface"
        aria-label={`No image for ${productName}`}
      />
    );
  }

  return (
    <div>
      {/* Mobile strip */}
      <div
        className="-mx-4 flex snap-x snap-mandatory gap-2 overflow-x-auto px-4 pb-2 sm:hidden"
        aria-label={`${productName} images`}
        role="region"
        tabIndex={0}
      >
        {images.map((image) => (
          <div
            key={image.url}
            className="relative aspect-[4/5] w-[85%] shrink-0 snap-center overflow-hidden rounded-lg bg-surface"
          >
            <Image
              src={image.url}
              alt={image.alt}
              fill
              sizes={STRIP_SIZES}
              className="object-cover"
            />
          </div>
        ))}
      </div>

      {/* Tablet / desktop */}
      <div className="hidden gap-4 sm:grid sm:grid-cols-[4.5rem_1fr]">
        <div className="flex flex-col gap-3" role="group" aria-label="Choose image">
          {images.map((image, index) => (
            <button
              key={image.url}
              type="button"
              onClick={() => setActive(index)}
              aria-label={`Show image ${index + 1} of ${images.length}`}
              aria-pressed={index === active}
              className={cn(
                "relative aspect-[4/5] overflow-hidden rounded-md bg-surface ring-offset-2 ring-offset-background transition",
                index === active ? "ring-1 ring-foreground" : "opacity-70 hover:opacity-100",
              )}
            >
              <Image src={image.url} alt="" fill sizes="72px" className="object-cover" />
            </button>
          ))}
        </div>
        <div className="relative aspect-[4/5] overflow-hidden rounded-lg bg-surface">
          <Image
            key={current.url}
            src={current.url}
            alt={current.alt}
            fill
            sizes={MAIN_SIZES}
            className="animate-fade-in object-cover"
          />
        </div>
      </div>
    </div>
  );
}
