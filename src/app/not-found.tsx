import type { Metadata } from "next";
import Link from "next/link";

import { StoreShell } from "@/components/layout/store-shell";
import { buttonClasses } from "@/components/ui/button";

export const metadata: Metadata = { title: "Page not found", robots: { index: false } };

export default function NotFound() {
  return (
    <StoreShell>
      <div className="mx-auto flex max-w-xl flex-col items-center px-4 py-24 text-center sm:py-32">
        <p className="text-xs font-medium tracking-[0.3em] text-accent uppercase">404</p>
        <h1 className="mt-4 text-3xl font-light tracking-tight sm:text-4xl">
          We couldn’t find that page
        </h1>
        <p className="mt-4 text-muted-foreground">
          The page may have moved, or the product is no longer available.
        </p>
        <div className="mt-10 flex flex-wrap justify-center gap-3">
          <Link href="/shop" className={buttonClasses()}>
            Browse the shop
          </Link>
          <Link href="/" className={buttonClasses({ variant: "outline" })}>
            Go home
          </Link>
        </div>
      </div>
    </StoreShell>
  );
}
