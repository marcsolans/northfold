import Link from "next/link";
import { HiXMark } from "react-icons/hi2";

import { formatMoney } from "@/lib/money";
import { CATEGORY_LABELS, PRODUCT_TYPE_LABELS } from "@/lib/navigation";
import { hasActiveFilters, type ShopUrlState, shopHref } from "@/lib/shop-url";

interface Chip {
  label: string;
  href: string;
}

function chipsFor(filters: ShopUrlState): Chip[] {
  const without = (next: Partial<ShopUrlState>) => shopHref({ ...filters, ...next, page: 1 });
  const chips: Chip[] = [];
  if (filters.q) chips.push({ label: `“${filters.q}”`, href: without({ q: undefined }) });
  for (const c of filters.category) {
    chips.push({
      label: CATEGORY_LABELS[c],
      href: without({ category: filters.category.filter((x) => x !== c) }),
    });
  }
  for (const t of filters.type) {
    chips.push({
      label: PRODUCT_TYPE_LABELS[t],
      href: without({ type: filters.type.filter((x) => x !== t) }),
    });
  }
  for (const s of filters.size) {
    chips.push({
      label: `Size ${s}`,
      href: without({ size: filters.size.filter((x) => x !== s) }),
    });
  }
  if (filters.minPrice !== undefined) {
    chips.push({
      label: `From ${formatMoney(filters.minPrice, { whole: true })}`,
      href: without({ minPrice: undefined }),
    });
  }
  if (filters.maxPrice !== undefined) {
    chips.push({
      label: `Up to ${formatMoney(filters.maxPrice, { whole: true })}`,
      href: without({ maxPrice: undefined }),
    });
  }
  if (filters.inStock) chips.push({ label: "In stock", href: without({ inStock: false }) });
  return chips;
}

export function countActiveFilters(filters: ShopUrlState): number {
  return chipsFor(filters).length;
}

export function ActiveFilters({ filters }: { filters: ShopUrlState }) {
  if (!hasActiveFilters(filters)) return null;
  return (
    <ul className="flex flex-wrap items-center gap-2" aria-label="Active filters">
      {chipsFor(filters).map((chip) => (
        <li key={chip.label}>
          <Link
            href={chip.href}
            scroll={false}
            className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card py-1 pr-2 pl-3 text-xs transition-colors hover:border-foreground"
          >
            {chip.label}
            <HiXMark aria-hidden="true" className="size-3.5" />
            <span className="sr-only">(remove filter)</span>
          </Link>
        </li>
      ))}
      <li>
        <Link
          href={shopHref({ sort: filters.sort })}
          scroll={false}
          className="text-xs text-muted-foreground underline underline-offset-4 hover:text-foreground"
        >
          Clear all
        </Link>
      </li>
    </ul>
  );
}
