import * as React from "react";

import { cn } from "../lib/cn";

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 rounded-md border border-dashed border-border-strong px-6 py-12 text-center",
        className,
      )}
    >
      {icon ? <div className="mb-1 text-fg-subtle [&_svg]:size-6">{icon}</div> : null}
      <p className="text-base font-semibold text-fg">{title}</p>
      {description ? <p className="max-w-md text-sm text-fg-muted">{description}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

export function ErrorState({
  title,
  description,
  onRetry,
  retryLabel = "Reintentar",
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  onRetry?: () => void;
  retryLabel?: string;
}) {
  return (
    <div role="alert" className="flex flex-col items-start gap-2 rounded-md border border-danger/25 bg-danger-soft px-4 py-3">
      <p className="text-sm font-semibold text-danger">{title}</p>
      {description ? <p className="text-sm text-fg-muted">{description}</p> : null}
      {onRetry ? (
        <button type="button" onClick={onRetry} className="text-sm font-medium text-danger underline underline-offset-4">
          {retryLabel}
        </button>
      ) : null}
    </div>
  );
}
