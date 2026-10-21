import Link from "next/link";
import { HiChevronLeft, HiChevronRight } from "react-icons/hi2";

import { cn } from "@/lib/utils";

/** Page numbers to show: always first/last, the current page ±1, gaps as null. */
function pageWindow(current: number, total: number): (number | null)[] {
  const pages = new Set([1, total, current - 1, current, current + 1]);
  const sorted = [...pages].filter((p) => p >= 1 && p <= total).sort((a, b) => a - b);
  const result: (number | null)[] = [];
  sorted.forEach((page, index) => {
    const previous = sorted[index - 1];
    if (previous !== undefined && page - previous > 1) result.push(null);
    result.push(page);
  });
  return result;
}

const item =
  "inline-flex h-10 min-w-10 items-center justify-center rounded-md px-3 text-sm transition-colors";

/** Page links. `hrefForPage` keeps every other URL parameter (filters, sort) intact. */
export function Pagination({
  page,
  totalPages,
  hrefForPage,
  className,
}: {
  page: number;
  totalPages: number;
  hrefForPage: (page: number) => string;
  className?: string;
}) {
  if (totalPages <= 1) return null;
  return (
    <nav
      aria-label="Pagination"
      className={cn("flex items-center justify-center gap-1", className)}
    >
      {page > 1 ? (
        <Link href={hrefForPage(page - 1)} className={cn(item, "hover:bg-surface")} rel="prev">
          <HiChevronLeft aria-hidden="true" className="size-4" />
          <span className="sr-only sm:not-sr-only sm:ml-1">Previous</span>
        </Link>
      ) : null}
      {pageWindow(page, totalPages).map((p, index) =>
        p === null ? (
          <span
            key={`gap-${index}`}
            className={cn(item, "text-muted-foreground")}
            aria-hidden="true"
          >
            …
          </span>
        ) : (
          <Link
            key={p}
            href={hrefForPage(p)}
            aria-current={p === page ? "page" : undefined}
            className={cn(
              item,
              p === page ? "bg-primary text-primary-foreground" : "hover:bg-surface",
            )}
          >
            <span className="sr-only">Page </span>
            {p}
          </Link>
        ),
      )}
      {page < totalPages ? (
        <Link href={hrefForPage(page + 1)} className={cn(item, "hover:bg-surface")} rel="next">
          <span className="sr-only sm:not-sr-only sm:mr-1">Next</span>
          <HiChevronRight aria-hidden="true" className="size-4" />
        </Link>
      ) : null}
    </nav>
  );
}
