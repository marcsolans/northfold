"use client";

import Link from "next/link";
import { useMemo } from "react";
import { HiOutlineShoppingBag } from "react-icons/hi2";

import { buttonClasses } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { formatMoney } from "@/lib/money";
import { PRICING } from "@/lib/store-config";
import { pluralize } from "@/lib/utils";
import { selectItemCount, selectTotals, useCartStore } from "@/stores/cart-store";

import { CartChanges } from "./cart-changes";
import { CartLineItem } from "./cart-line-item";
import { OrderSummary } from "./order-summary";
import { useValidatedCart } from "./use-validated-cart";

function CartSkeleton() {
  return (
    <div
      aria-busy="true"
      aria-label="Loading your bag"
      className="grid gap-10 lg:grid-cols-[1fr_22rem]"
    >
      <div className="divide-y divide-border">
        {Array.from({ length: 2 }, (_, i) => (
          <div key={i} className="flex gap-6 py-6">
            <Skeleton className="aspect-[4/5] w-28" />
            <div className="flex-1 space-y-3">
              <Skeleton className="h-4 w-1/2" />
              <Skeleton className="h-4 w-1/3" />
            </div>
          </div>
        ))}
      </div>
      <Skeleton className="h-72" />
    </div>
  );
}

export function CartView() {
  const { status, changes } = useValidatedCart();
  const lines = useCartStore((state) => state.lines);
  const count = useCartStore(selectItemCount);
  // Derived with useMemo: a selector returning a new object would re-render forever.
  const totals = useMemo(() => selectTotals({ lines }), [lines]);

  if (status === "validating" && lines.length === 0) return <CartSkeleton />;

  if (lines.length === 0) {
    return (
      <div className="space-y-6">
        <CartChanges changes={changes} />
        <EmptyState
          icon={<HiOutlineShoppingBag />}
          title="Your bag is empty"
          description={`Find something you love — free shipping on orders over ${formatMoney(
            PRICING.freeShippingThreshold,
            { whole: true },
          )}.`}
          action={
            <Link href="/shop" className={buttonClasses()}>
              Start shopping
            </Link>
          }
        />
      </div>
    );
  }

  const validating = status === "validating";

  return (
    <div className="space-y-6">
      <CartChanges changes={changes} />
      {status === "error" ? (
        <p
          role="alert"
          className="rounded-md bg-destructive-soft px-4 py-3 text-sm text-destructive"
        >
          We couldn’t check your bag against current stock. Prices and availability are confirmed at
          checkout.
        </p>
      ) : null}
      <div className="grid items-start gap-10 lg:grid-cols-[1fr_22rem]">
        <section aria-labelledby="cart-items-heading">
          <h2 id="cart-items-heading" className="sr-only">
            Items ({pluralize(count, "item")})
          </h2>
          <ul className="divide-y divide-border border-y border-border">
            {lines.map((line) => (
              <CartLineItem key={line.variantId} line={line} disabled={validating} />
            ))}
          </ul>
          <Link href="/shop" className="mt-6 inline-block text-sm underline underline-offset-4">
            Continue shopping
          </Link>
        </section>
        <aside className="lg:sticky lg:top-24">
          <OrderSummary totals={totals} showFreeShippingHint>
            {validating ? (
              <span
                className={buttonClasses({ size: "lg", className: "w-full opacity-60" })}
                aria-disabled="true"
              >
                Checking availability…
              </span>
            ) : (
              <Link href="/checkout" className={buttonClasses({ size: "lg", className: "w-full" })}>
                Proceed to checkout
              </Link>
            )}
            <p className="mt-4 text-center text-xs text-muted-foreground">
              Pay by card with Stripe, or cash on delivery.
            </p>
          </OrderSummary>
        </aside>
      </div>
    </div>
  );
}
