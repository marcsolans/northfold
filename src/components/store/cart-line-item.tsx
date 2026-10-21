"use client";

import Image from "next/image";
import Link from "next/link";

import { formatMoney, lineTotal } from "@/lib/money";
import { CATALOG } from "@/lib/store-config";
import { type CartLine, useCartStore } from "@/stores/cart-store";

import { QuantitySelector } from "./quantity-selector";

export function CartLineItem({ line, disabled = false }: { line: CartLine; disabled?: boolean }) {
  const setQuantity = useCartStore((state) => state.setQuantity);
  const removeItem = useCartStore((state) => state.removeItem);
  const { snapshot } = line;
  const max = Math.min(snapshot.available, CATALOG.maxQuantityPerLine);

  return (
    <li className="flex gap-4 py-6 sm:gap-6">
      <Link
        href={`/products/${snapshot.productSlug}`}
        className="relative aspect-[4/5] w-24 shrink-0 overflow-hidden rounded-md bg-surface sm:w-28"
        tabIndex={-1}
        aria-hidden="true"
      >
        {snapshot.imageUrl ? (
          <Image src={snapshot.imageUrl} alt="" fill sizes="112px" className="object-cover" />
        ) : null}
      </Link>
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h3 className="text-sm font-medium">
              <Link href={`/products/${snapshot.productSlug}`} className="hover:underline">
                {snapshot.productName}
              </Link>
            </h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Size {snapshot.size} · {snapshot.colorName}
            </p>
            <p className="mt-1 text-sm text-muted-foreground">
              {formatMoney(snapshot.unitPrice)} each
            </p>
          </div>
          <p className="shrink-0 text-sm font-medium tabular-nums">
            {formatMoney(lineTotal(snapshot.unitPrice, line.quantity))}
          </p>
        </div>
        <div className="mt-auto flex items-center justify-between gap-4 pt-4">
          <QuantitySelector
            size="sm"
            value={line.quantity}
            max={max}
            disabled={disabled}
            label={`Quantity of ${snapshot.productName}`}
            onChange={(quantity) => setQuantity(line.variantId, quantity)}
          />
          <button
            type="button"
            disabled={disabled}
            onClick={() => removeItem(line.variantId)}
            className="text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline disabled:opacity-50"
          >
            Remove<span className="sr-only"> {snapshot.productName}</span>
          </button>
        </div>
        {line.quantity >= max && max < CATALOG.maxQuantityPerLine ? (
          <p className="mt-2 text-xs text-warning">Only {snapshot.available} available</p>
        ) : null}
      </div>
    </li>
  );
}
