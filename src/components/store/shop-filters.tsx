"use client";

import { useRouter } from "next/navigation";
import {
  type FormEvent,
  type ReactNode,
  useId,
  useOptimistic,
  useState,
  useTransition,
} from "react";

import { Button } from "@/components/ui/button";
import { Category, ProductType, Size } from "@/generated/prisma/enums";
import { CATEGORY_LABELS, PRODUCT_TYPE_LABELS } from "@/lib/navigation";
import { type ShopUrlState, shopHref, toggleValue } from "@/lib/shop-url";
import { cn } from "@/lib/utils";

function FilterGroup({ legend, children }: { legend: string; children: ReactNode }) {
  return (
    <div className="border-t border-border py-5 first:border-t-0 first:pt-0">
      <fieldset>
        <legend className="mb-3 text-xs font-medium tracking-[0.2em] uppercase">{legend}</legend>
        {children}
      </fieldset>
    </div>
  );
}

function CheckOption({
  name,
  value,
  label,
  checked,
  onChange,
}: {
  name: string;
  value: string;
  label: string;
  checked: boolean;
  onChange: () => void;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-3 py-1.5 text-sm text-foreground">
      <input
        type="checkbox"
        name={name}
        value={value}
        checked={checked}
        onChange={onChange}
        className="size-4 rounded-sm border-input accent-accent"
      />
      {label}
    </label>
  );
}

/**
 * Shop filters. Every change is written to the URL (shareable, survives refresh); the server
 * page re-renders from the URL. Without JavaScript the panel still works as a GET form.
 */
export function ShopFilters({
  filters: committed,
  onApplied,
}: {
  filters: ShopUrlState;
  onApplied?: () => void;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  // Reflect a click immediately while the new results load.
  const [filters, setOptimisticFilters] = useOptimistic(committed);
  const priceId = useId();
  const [minPrice, setMinPrice] = useState(filters.minPrice?.toString() ?? "");
  const [maxPrice, setMaxPrice] = useState(filters.maxPrice?.toString() ?? "");

  function apply(next: Partial<ShopUrlState>) {
    const state = { ...filters, ...next, page: 1 };
    startTransition(() => {
      setOptimisticFilters(state);
      router.push(shopHref(state), { scroll: false });
    });
  }

  function parsePrice(value: string): number | undefined {
    const parsed = Number(value);
    return value.trim() !== "" && Number.isFinite(parsed) && parsed >= 0
      ? Math.floor(parsed)
      : undefined;
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    apply({ minPrice: parsePrice(minPrice), maxPrice: parsePrice(maxPrice) });
    onApplied?.();
  }

  return (
    <form
      action="/shop"
      method="get"
      onSubmit={onSubmit}
      aria-busy={pending}
      className={cn(pending && "opacity-70")}
    >
      {filters.q ? <input type="hidden" name="q" value={filters.q} /> : null}
      {filters.sort !== "newest" ? <input type="hidden" name="sort" value={filters.sort} /> : null}

      <FilterGroup legend="Category">
        {Object.values(Category).map((category) => (
          <CheckOption
            key={category}
            name="category"
            value={category.toLowerCase()}
            label={CATEGORY_LABELS[category]}
            checked={filters.category.includes(category)}
            onChange={() => apply({ category: toggleValue(filters.category, category) })}
          />
        ))}
      </FilterGroup>

      <FilterGroup legend="Product type">
        {Object.values(ProductType).map((type) => (
          <CheckOption
            key={type}
            name="type"
            value={type.toLowerCase()}
            label={PRODUCT_TYPE_LABELS[type]}
            checked={filters.type.includes(type)}
            onChange={() => apply({ type: toggleValue(filters.type, type) })}
          />
        ))}
      </FilterGroup>

      <FilterGroup legend="Size">
        <div className="grid grid-cols-3 gap-2">
          {Object.values(Size).map((size) => {
            const checked = filters.size.includes(size);
            return (
              <label
                key={size}
                className={cn(
                  "flex h-10 cursor-pointer items-center justify-center rounded-md border text-sm transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent",
                  checked
                    ? "border-foreground bg-primary text-primary-foreground"
                    : "border-input bg-card hover:border-foreground",
                )}
              >
                <input
                  type="checkbox"
                  name="size"
                  value={size}
                  checked={checked}
                  onChange={() => apply({ size: toggleValue(filters.size, size) })}
                  className="sr-only"
                />
                {size}
              </label>
            );
          })}
        </div>
      </FilterGroup>

      <FilterGroup legend="Price (USD)">
        <div className="flex items-center gap-2">
          <label className="sr-only" htmlFor={`${priceId}-min`}>
            Minimum price
          </label>
          <input
            id={`${priceId}-min`}
            name="minPrice"
            inputMode="numeric"
            placeholder="Min"
            value={minPrice}
            onChange={(event) => setMinPrice(event.target.value)}
            className="h-10 w-full rounded-md border border-input bg-card px-3 text-sm focus-visible:border-foreground focus-visible:outline-none"
          />
          <span aria-hidden="true" className="text-muted-foreground">
            –
          </span>
          <label className="sr-only" htmlFor={`${priceId}-max`}>
            Maximum price
          </label>
          <input
            id={`${priceId}-max`}
            name="maxPrice"
            inputMode="numeric"
            placeholder="Max"
            value={maxPrice}
            onChange={(event) => setMaxPrice(event.target.value)}
            className="h-10 w-full rounded-md border border-input bg-card px-3 text-sm focus-visible:border-foreground focus-visible:outline-none"
          />
        </div>
      </FilterGroup>

      <FilterGroup legend="Availability">
        <CheckOption
          name="inStock"
          value="1"
          label="In stock only"
          checked={filters.inStock}
          onChange={() => apply({ inStock: !filters.inStock })}
        />
      </FilterGroup>

      <Button type="submit" variant="outline" className="mt-2 w-full" loading={pending}>
        Apply filters
      </Button>
    </form>
  );
}
