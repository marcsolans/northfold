import { Inbox } from "lucide-react";
import * as React from "react";

import { cn } from "../../lib/cn";
import { Skeleton } from "../skeleton";

export interface DataStateLabels {
  loading: string;
  empty: string;
  errorTitle: string;
  retry: string;
}

export interface DataStatusProps {
  loading?: boolean;
  error?: string | null;
  empty?: boolean;
  labels: DataStateLabels;
  emptyText?: string | null;
  onRetry?: () => void;
  skeleton?: React.ReactNode;
  className?: string;
  children?: React.ReactNode;
}

/** Loading, error and empty states shared by every data component. */
export function DataStatus({
  loading,
  error,
  empty,
  labels,
  emptyText,
  onRetry,
  skeleton,
  className,
  children,
}: DataStatusProps) {
  if (loading) {
    return (
      <div role="status" aria-label={labels.loading} className={cn("flex flex-col gap-2", className)}>
        {skeleton ?? (
          <>
            <Skeleton className="h-7 w-full" />
            <Skeleton className="h-7 w-11/12" />
            <Skeleton className="h-7 w-4/5" />
          </>
        )}
      </div>
    );
  }
  if (error) {
    return (
      <div role="alert" className={cn("flex flex-col items-start gap-1.5 rounded-md border border-danger/25 bg-danger-soft px-3 py-2.5", className)}>
        <p className="text-sm font-semibold text-danger">{labels.errorTitle}</p>
        <p className="text-sm text-fg-muted">{error}</p>
        {onRetry ? (
          <button type="button" onClick={onRetry} className="text-sm font-medium text-danger underline underline-offset-4">
            {labels.retry}
          </button>
        ) : null}
      </div>
    );
  }
  if (empty) {
    return (
      <div className={cn("flex flex-1 flex-col items-center justify-center gap-1.5 py-6 text-center text-fg-subtle", className)}>
        <Inbox className="size-5" aria-hidden />
        <p className="text-sm">{emptyText || labels.empty}</p>
      </div>
    );
  }
  return <>{children}</>;
}

/** Frame of a component on a dashboard: title, optional description and actions, content. */
export function DataPanel({
  title,
  description,
  actions,
  className,
  bodyClassName,
  children,
}: {
  title?: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
  bodyClassName?: string;
  children: React.ReactNode;
}) {
  return (
    <section
      aria-label={typeof title === "string" ? title : undefined}
      className={cn("flex h-full min-h-0 flex-col overflow-hidden rounded-md border border-border bg-surface", className)}
    >
      {title || actions ? (
        <header className="flex min-h-10 items-center justify-between gap-2 border-b border-border px-3 py-2">
          <div className="min-w-0">
            {title ? <h3 className="truncate text-sm font-semibold text-fg">{title}</h3> : null}
            {description ? <p className="truncate text-xs text-fg-muted">{description}</p> : null}
          </div>
          {actions ? <div className="flex shrink-0 items-center gap-1.5">{actions}</div> : null}
        </header>
      ) : null}
      <div className={cn("flex min-h-0 flex-1 flex-col overflow-auto p-3", bodyClassName)}>{children}</div>
    </section>
  );
}
