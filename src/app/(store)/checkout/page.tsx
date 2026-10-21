import type { Metadata } from "next";
import { Suspense } from "react";

import { CheckoutForm } from "@/components/store/checkout-form";
import { Skeleton } from "@/components/ui/skeleton";
import { features } from "@/env";
import { requireUserPage } from "@/server/auth/session";
import { getUserAddresses } from "@/server/queries/addresses";

export const metadata: Metadata = { title: "Checkout", robots: { index: false } };

async function CheckoutContent() {
  const user = await requireUserPage("/checkout");
  const addresses = await getUserAddresses(user.id);
  return <CheckoutForm key={user.id} addresses={addresses} stripeEnabled={features.stripe} />;
}

export default function CheckoutPage() {
  return (
    <div className="mx-auto max-w-6xl px-4 pt-10 pb-16 sm:px-6">
      <h1 className="mb-8 text-3xl font-light tracking-tight sm:text-4xl">Checkout</h1>
      <Suspense
        fallback={
          <div aria-busy="true" className="grid gap-10 lg:grid-cols-[1fr_24rem]">
            <Skeleton className="h-96" />
            <Skeleton className="h-80" />
          </div>
        }
      >
        <CheckoutContent />
      </Suspense>
    </div>
  );
}
