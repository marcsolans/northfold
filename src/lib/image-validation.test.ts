import { describe, expect, it } from "vitest";

import { checkImageFile, isAllowedImageUrl, sniffImageType } from "./image-validation";

const jpeg = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0, 0, 0, 0, 0, 0, 0, 0]);
const png = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 0]);
const webp = new TextEncoder().encode("RIFF\0\0\0\0WEBPVP8 ");
const avif = new TextEncoder().encode("\0\0\0\x1cftypavif");
const html = new TextEncoder().encode("<html><script>");

describe("sniffImageType", () => {
  it("recognises the allowed formats by their magic bytes", () => {
    expect(sniffImageType(jpeg)).toBe("image/jpeg");
    expect(sniffImageType(png)).toBe("image/png");
    expect(sniffImageType(webp)).toBe("image/webp");
    expect(sniffImageType(avif)).toBe("image/avif");
    expect(sniffImageType(html)).toBeNull();
  });
});

describe("checkImageFile", () => {
  it("accepts a real image within the size limit", () => {
    expect(checkImageFile("image/png", 1024, png)).toEqual({ ok: true, type: "image/png" });
  });

  it("rejects disallowed types, oversized files and disguised content", () => {
    expect(checkImageFile("image/gif", 1024, png).ok).toBe(false);
    expect(checkImageFile("image/png", 6 * 1024 * 1024, png).ok).toBe(false);
    expect(checkImageFile("image/png", 0, png).ok).toBe(false);
    expect(checkImageFile("image/jpeg", 1024, html)).toEqual({
      ok: false,
      error: "The file content does not match its image type.",
    });
  });
});

describe("isAllowedImageUrl", () => {
  it("only allows https URLs on the configured hosts", () => {
    expect(isAllowedImageUrl("https://res.cloudinary.com/demo/image/upload/a.jpg")).toBe(true);
    expect(isAllowedImageUrl("https://images.unsplash.com/photo-1")).toBe(true);
    expect(isAllowedImageUrl("http://images.unsplash.com/photo-1")).toBe(false);
    expect(isAllowedImageUrl("https://evil.example.com/a.jpg")).toBe(false);
    expect(isAllowedImageUrl("javascript:alert(1)")).toBe(false);
  });
});
