import { type ReactNode } from "react";

import { CartHydrator } from "@/components/store/cart-hydrator";

import { Footer } from "./footer";
import { Navbar } from "./navbar";

/** Storefront chrome shared by the store, account and checkout routes. Never used in /admin. */
export function StoreShell({ children }: { children: ReactNode }) {
  return (
    <>
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-primary px-4 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        Skip to content
      </a>
      <CartHydrator />
      <Navbar />
      <main id="main" className="flex-1">
        {children}
      </main>
      <Footer />
    </>
  );
}
