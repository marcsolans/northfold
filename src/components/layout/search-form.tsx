import Form from "next/form";
import { HiMagnifyingGlass } from "react-icons/hi2";

import { cn } from "@/lib/utils";

/** GET search into the shop; works without JavaScript and navigates client-side with it. */
export function SearchForm({ className, id = "site-search" }: { className?: string; id?: string }) {
  return (
    <Form action="/shop" role="search" className={cn("relative", className)}>
      <label htmlFor={id} className="sr-only">
        Search products
      </label>
      <HiMagnifyingGlass
        aria-hidden="true"
        className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
      />
      <input
        id={id}
        name="q"
        type="search"
        placeholder="Search"
        autoComplete="off"
        maxLength={100}
        className="h-10 w-full rounded-full border border-border bg-card pr-4 pl-9 text-sm placeholder:text-muted-foreground focus-visible:border-foreground focus-visible:outline-none"
      />
    </Form>
  );
}
