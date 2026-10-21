import Link from "next/link";

import { buttonClasses } from "@/components/ui/button";

export default function AdminNotFound() {
  return (
    <div className="py-16 text-center">
      <p className="text-xs font-medium tracking-[0.3em] text-accent uppercase">404</p>
      <h1 className="mt-4 text-2xl font-light tracking-tight sm:text-3xl">Not found</h1>
      <p className="mt-3 text-sm text-muted-foreground">
        This product or order does not exist. It may have been deleted.
      </p>
      <div className="mt-8 flex flex-wrap justify-center gap-3">
        <Link href="/admin/products" className={buttonClasses({ variant: "outline" })}>
          Products
        </Link>
        <Link href="/admin/orders" className={buttonClasses({ variant: "outline" })}>
          Orders
        </Link>
      </div>
    </div>
  );
}
