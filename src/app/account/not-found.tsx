import Link from "next/link";

import { buttonClasses } from "@/components/ui/button";

export default function AccountNotFound() {
  return (
    <div className="py-12 text-center">
      <p className="text-xs font-medium tracking-[0.3em] text-accent uppercase">404</p>
      <h1 className="mt-4 text-2xl font-light tracking-tight sm:text-3xl">
        We couldn’t find that order
      </h1>
      <p className="mt-3 text-sm text-muted-foreground">
        It may belong to another account, or the link is incomplete.
      </p>
      <Link
        href="/account/orders"
        className={buttonClasses({ variant: "outline", className: "mt-8" })}
      >
        Your orders
      </Link>
    </div>
  );
}
