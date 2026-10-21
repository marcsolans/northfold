import type { Metadata } from "next";

import { CartView } from "@/components/store/cart-view";

export const metadata: Metadata = {
  title: "Your bag",
  robots: { index: false },
};

export default function CartPage() {
  return (
    <div className="mx-auto max-w-6xl px-4 pt-10 pb-16 sm:px-6">
      <h1 className="mb-8 text-3xl font-light tracking-tight sm:text-4xl">Your bag</h1>
      <CartView />
    </div>
  );
}
