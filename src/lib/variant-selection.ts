import { Size } from "@/generated/prisma/enums";

export interface SelectableVariant {
  id: string;
  size: Size;
  colorName: string;
  colorHex: string;
  stock: number;
}

export interface ColorOption {
  name: string;
  hex: string;
  inStock: boolean;
}

export interface SizeOption {
  size: Size;
  variant: SelectableVariant | undefined;
  /** The combination exists for the selected colour and has stock. */
  available: boolean;
}

const SIZE_ORDER: readonly Size[] = Object.values(Size);

/** Colours in first-seen order, flagged when any size is in stock. */
export function colorOptions(variants: readonly SelectableVariant[]): ColorOption[] {
  const options = new Map<string, ColorOption>();
  for (const variant of variants) {
    const existing = options.get(variant.colorName);
    options.set(variant.colorName, {
      name: variant.colorName,
      hex: variant.colorHex,
      inStock: (existing?.inStock ?? false) || variant.stock > 0,
    });
  }
  return [...options.values()];
}

/** Every size the product comes in (any colour), with availability for the selected colour. */
export function sizeOptions(
  variants: readonly SelectableVariant[],
  colorName: string | null,
): SizeOption[] {
  const sizes = SIZE_ORDER.filter((size) => variants.some((variant) => variant.size === size));
  return sizes.map((size) => {
    const variant = variants.find((v) => v.size === size && v.colorName === colorName);
    return { size, variant, available: Boolean(variant && variant.stock > 0) };
  });
}

export function findVariant(
  variants: readonly SelectableVariant[],
  colorName: string | null,
  size: Size | null,
): SelectableVariant | undefined {
  if (!colorName || !size) return undefined;
  return variants.find((variant) => variant.colorName === colorName && variant.size === size);
}

/** The first colour with stock (or the first colour when everything is sold out). */
export function initialColor(variants: readonly SelectableVariant[]): string | null {
  const options = colorOptions(variants);
  return (options.find((option) => option.inStock) ?? options[0])?.name ?? null;
}
