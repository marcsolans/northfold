"use client";

import Link from "next/link";
import { useState } from "react";
import toast from "react-hot-toast";

import { Button } from "@/components/ui/button";
import type { Size } from "@/generated/prisma/enums";
import { type MoneyString } from "@/lib/money";
import { CATALOG } from "@/lib/store-config";
import { cn } from "@/lib/utils";
import { colorOptions, findVariant, initialColor, sizeOptions } from "@/lib/variant-selection";
import type { ProductDetailDTO } from "@/server/queries/catalog";
import { useCartStore } from "@/stores/cart-store";

import { QuantitySelector } from "./quantity-selector";

interface Props {
  product: Pick<ProductDetailDTO, "id" | "slug" | "name" | "variants"> & {
    price: MoneyString;
    imageUrl: string | null;
  };
}

/**
 * Colour → size → quantity → add to bag. Only combinations that exist and are in stock can be
 * chosen, and the quantity is capped at the available stock.
 */
export function ProductPurchase({ product }: Props) {
  const [color, setColor] = useState<string | null>(() => initialColor(product.variants));
  const [size, setSize] = useState<Size | null>(null);
  const [quantity, setQuantity] = useState(1);
  const addItem = useCartStore((state) => state.addItem);

  const colors = colorOptions(product.variants);
  const sizes = sizeOptions(product.variants, color);
  const variant = findVariant(product.variants, color, size);
  const soldOut = colors.every((option) => !option.inStock);
  const maxQuantity = Math.min(variant?.stock ?? 1, CATALOG.maxQuantityPerLine);

  function chooseColor(name: string) {
    setColor(name);
    const stillAvailable = sizeOptions(product.variants, name).some(
      (o) => o.size === size && o.available,
    );
    if (!stillAvailable) setSize(null);
    setQuantity(1);
  }

  function addToCart() {
    if (!variant || variant.stock <= 0) return;
    const inCart =
      useCartStore.getState().lines.find((line) => line.variantId === variant.id)?.quantity ?? 0;
    const room = Math.min(variant.stock, CATALOG.maxQuantityPerLine) - inCart;
    if (room <= 0) {
      toast.error(`You already have the maximum available (${inCart}) in your bag.`);
      return;
    }
    const added = Math.min(quantity, room);
    addItem(
      variant.id,
      {
        productId: product.id,
        productName: product.name,
        productSlug: product.slug,
        imageUrl: product.imageUrl,
        size: variant.size,
        colorName: variant.colorName,
        unitPrice: product.price,
        available: variant.stock,
      },
      added,
    );
    toast.success((t) => (
      <span className="flex items-center gap-3">
        {added < quantity
          ? `Only ${added} more available — added to your bag`
          : "Added to your bag"}
        <Link
          href="/cart"
          onClick={() => toast.dismiss(t.id)}
          className="font-medium underline underline-offset-4"
        >
          View bag
        </Link>
      </span>
    ));
    setQuantity(1);
  }

  return (
    <div className="space-y-7">
      <fieldset>
        <legend className="mb-3 text-sm">
          <span className="font-medium">Colour</span>
          <span className="ml-2 text-muted-foreground">{color}</span>
        </legend>
        <div className="flex flex-wrap gap-3">
          {colors.map((option) => (
            <label
              key={option.name}
              title={option.inStock ? option.name : `${option.name} (sold out)`}
              className={cn(
                "relative flex size-10 cursor-pointer items-center justify-center rounded-full border transition has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent",
                option.name === color
                  ? "border-foreground"
                  : "border-transparent hover:border-input",
                !option.inStock && "cursor-not-allowed opacity-40",
              )}
            >
              <input
                type="radio"
                name="color"
                value={option.name}
                checked={option.name === color}
                disabled={!option.inStock}
                onChange={() => chooseColor(option.name)}
                className="sr-only"
                aria-label={option.inStock ? option.name : `${option.name}, sold out`}
              />
              <span
                aria-hidden="true"
                className="size-7 rounded-full border border-foreground/15"
                style={{ backgroundColor: option.hex }}
              />
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset>
        <legend className="mb-3 text-sm font-medium">Size</legend>
        <div className="grid grid-cols-4 gap-2 sm:grid-cols-6">
          {sizes.map((option) => (
            <label
              key={option.size}
              className={cn(
                "flex h-11 items-center justify-center rounded-md border text-sm transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent",
                !option.available
                  ? "cursor-not-allowed border-border text-muted-foreground/60 line-through"
                  : option.size === size
                    ? "cursor-pointer border-foreground bg-primary text-primary-foreground"
                    : "cursor-pointer border-input bg-card hover:border-foreground",
              )}
            >
              <input
                type="radio"
                name="size"
                value={option.size}
                checked={option.size === size}
                disabled={!option.available}
                onChange={() => {
                  setSize(option.size);
                  setQuantity(1);
                }}
                className="sr-only"
                aria-label={
                  option.available ? `Size ${option.size}` : `Size ${option.size}, unavailable`
                }
              />
              {option.size}
            </label>
          ))}
        </div>
        <p className="mt-3 min-h-5 text-sm" aria-live="polite">
          {variant && variant.stock > 0 && variant.stock <= CATALOG.lowStockThreshold ? (
            <span className="text-warning">Only {variant.stock} left in this size</span>
          ) : variant ? (
            <span className="text-success">In stock</span>
          ) : null}
        </p>
      </fieldset>

      <div className="flex gap-3">
        <QuantitySelector
          value={quantity}
          max={maxQuantity}
          onChange={setQuantity}
          disabled={!variant}
        />
        <Button
          size="lg"
          className="flex-1"
          onClick={addToCart}
          disabled={soldOut || !variant || variant.stock <= 0}
        >
          {soldOut ? "Out of stock" : variant ? "Add to bag" : "Select a size"}
        </Button>
      </div>
    </div>
  );
}
