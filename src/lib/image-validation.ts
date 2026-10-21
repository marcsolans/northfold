export const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
export const ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp", "image/avif"] as const;
export type AllowedImageType = (typeof ALLOWED_IMAGE_TYPES)[number];

/** Detects the real format from the file's first bytes; the declared MIME type can lie. */
export function sniffImageType(bytes: Uint8Array): AllowedImageType | null {
  const ascii = (start: number, end: number) => String.fromCharCode(...bytes.subarray(start, end));
  if (bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) return "image/jpeg";
  if (bytes[0] === 0x89 && ascii(1, 4) === "PNG") return "image/png";
  if (ascii(0, 4) === "RIFF" && ascii(8, 12) === "WEBP") return "image/webp";
  if (ascii(4, 8) === "ftyp" && ["avif", "avis"].includes(ascii(8, 12))) return "image/avif";
  return null;
}

export type ImageCheck = { ok: true; type: AllowedImageType } | { ok: false; error: string };

export function checkImageFile(declaredType: string, size: number, head: Uint8Array): ImageCheck {
  if (size === 0) return { ok: false, error: "The file is empty." };
  if (size > MAX_IMAGE_BYTES) return { ok: false, error: "Images must be 5 MB or smaller." };
  if (!(ALLOWED_IMAGE_TYPES as readonly string[]).includes(declaredType)) {
    return { ok: false, error: "Use a JPEG, PNG, WebP or AVIF image." };
  }
  const sniffed = sniffImageType(head);
  if (sniffed !== declaredType) {
    return { ok: false, error: "The file content does not match its image type." };
  }
  return { ok: true, type: sniffed };
}

/** Hosts product image URLs may point to (must match next.config remotePatterns). */
export const ALLOWED_IMAGE_HOSTS = ["res.cloudinary.com", "images.unsplash.com"] as const;

export function isAllowedImageUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return (
      url.protocol === "https:" && (ALLOWED_IMAGE_HOSTS as readonly string[]).includes(url.hostname)
    );
  } catch {
    return false;
  }
}
