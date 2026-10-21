"use client";

import { useEffect, useRef, useState } from "react";
import { HiAdjustmentsHorizontal, HiXMark } from "react-icons/hi2";

import { Button } from "@/components/ui/button";
import type { ShopUrlState } from "@/lib/shop-url";

import { ShopFilters } from "./shop-filters";

/** Filters in a modal sheet for small screens. */
export function MobileFilters({
  filters,
  activeCount,
}: {
  filters: ShopUrlState;
  activeCount: number;
}) {
  const [open, setOpen] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  useEffect(() => {
    const dialog = dialogRef.current;
    return () => dialog?.close();
  }, []);

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        className="lg:hidden"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen(true)}
      >
        <HiAdjustmentsHorizontal aria-hidden="true" className="size-4" />
        Filters{activeCount > 0 ? ` (${activeCount})` : ""}
      </Button>
      <dialog
        ref={dialogRef}
        aria-label="Filters"
        onClose={() => setOpen(false)}
        onClick={(event) => {
          if (event.target === event.currentTarget) setOpen(false);
        }}
        className="mt-auto mb-0 max-h-[85dvh] w-full max-w-none rounded-t-xl bg-background p-0 text-foreground backdrop:bg-foreground/40 open:animate-fade-in"
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border bg-background px-5 py-4">
          <h2 className="text-base font-medium">Filters</h2>
          <button
            type="button"
            onClick={() => setOpen(false)}
            aria-label="Close filters"
            className="inline-flex size-10 items-center justify-center rounded-full hover:bg-surface"
          >
            <HiXMark aria-hidden="true" className="size-6" />
          </button>
        </div>
        <div className="px-5 py-5">
          <ShopFilters filters={filters} onApplied={() => setOpen(false)} />
        </div>
      </dialog>
    </>
  );
}
