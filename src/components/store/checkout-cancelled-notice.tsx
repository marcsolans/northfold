"use client";

import { useSearchParams } from "next/navigation";

/** Shown when Stripe sends the customer back via the cancel URL. */
export function CheckoutCancelledNotice() {
  const cancelled = useSearchParams().get("checkout") === "cancelled";
  if (!cancelled) return null;
  return (
    <p
      role="status"
      className="mb-6 rounded-lg border border-border bg-card px-5 py-4 text-sm text-muted-foreground"
    >
      Payment cancelled — you have not been charged. Your bag is saved whenever you’re ready.
    </p>
  );
}
