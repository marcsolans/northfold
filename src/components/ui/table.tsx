import { type HTMLAttributes, type TdHTMLAttributes, type ThHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

/**
 * Horizontally scrollable on small screens so wide admin tables never break the layout. The
 * scroll container is a named, focusable region so keyboard users can scroll it too.
 */
export function Table({
  label,
  className,
  ...props
}: HTMLAttributes<HTMLTableElement> & { label: string }) {
  return (
    <div
      role="region"
      aria-label={label}
      tabIndex={0}
      className="w-full overflow-x-auto rounded-lg border border-border bg-card focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
    >
      <table
        className={cn("w-full min-w-max border-collapse text-left text-sm", className)}
        {...props}
      />
    </div>
  );
}

export function TableHead({ className, ...props }: HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className={cn("border-b border-border bg-surface/60", className)} {...props} />;
}

export function TableBody({ className, ...props }: HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={cn("divide-y divide-border", className)} {...props} />;
}

export function TableRow({ className, ...props }: HTMLAttributes<HTMLTableRowElement>) {
  return <tr className={cn("transition-colors hover:bg-surface/40", className)} {...props} />;
}

export function TableHeaderCell({ className, ...props }: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      scope="col"
      className={cn(
        "px-4 py-3 text-xs font-medium tracking-wide text-muted-foreground uppercase",
        className,
      )}
      {...props}
    />
  );
}

export function TableCell({ className, ...props }: TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn("px-4 py-3 align-middle", className)} {...props} />;
}
