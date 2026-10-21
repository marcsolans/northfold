"use client";

import { useRouter } from "next/navigation";
import { useOptimistic, useTransition } from "react";

import { Select } from "@/components/ui/select";
import { SORT_LABELS } from "@/lib/navigation";
import { type ShopUrlState, shopHref } from "@/lib/shop-url";
import { SORT_OPTIONS, type SortOption } from "@/lib/validators/catalog";

function isSortOption(value: string): value is SortOption {
  return (SORT_OPTIONS as readonly string[]).includes(value);
}

export function SortSelect({ filters }: { filters: ShopUrlState }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [sort, setOptimisticSort] = useOptimistic(filters.sort);

  return (
    <div className="flex items-center gap-3">
      <label htmlFor="shop-sort" className="hidden text-sm text-muted-foreground sm:block">
        Sort by
      </label>
      <Select
        id="shop-sort"
        aria-label="Sort products"
        className="w-48"
        value={sort}
        aria-busy={pending}
        options={SORT_OPTIONS.map((option) => ({ value: option, label: SORT_LABELS[option] }))}
        onChange={(event) => {
          const next = event.target.value;
          if (!isSortOption(next)) return;
          startTransition(() => {
            setOptimisticSort(next);
            router.push(shopHref({ ...filters, sort: next, page: 1 }), { scroll: false });
          });
        }}
      />
    </div>
  );
}
