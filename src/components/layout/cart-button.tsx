"use client";

import Link from "next/link";
import { HiOutlineShoppingBag } from "react-icons/hi2";

import { useCartHydrated } from "@/components/store/cart-hydrator";
import { pluralize } from "@/lib/utils";
import { selectItemCount, useCartStore } from "@/stores/cart-store";

export function CartButton() {
  const hydrated = useCartHydrated();
  const count = useCartStore(selectItemCount);
  const visibleCount = hydrated ? count : 0;

  return (
    <Link
      href="/cart"
      className="relative inline-flex size-10 items-center justify-center rounded-full transition-colors hover:bg-surface"
      aria-label={visibleCount > 0 ? `Cart, ${pluralize(visibleCount, "item")}` : "Cart"}
    >
      <HiOutlineShoppingBag aria-hidden="true" className="size-[1.375rem]" />
      {visibleCount > 0 ? (
        <span
          aria-hidden="true"
          data-testid="cart-count"
          className="absolute top-0.5 right-0.5 flex h-[1.1rem] min-w-[1.1rem] animate-fade-in items-center justify-center rounded-full bg-accent px-1 text-[0.65rem] font-semibold text-accent-foreground"
        >
          {visibleCount > 99 ? "99+" : visibleCount}
        </span>
      ) : null}
    </Link>
  );
}
