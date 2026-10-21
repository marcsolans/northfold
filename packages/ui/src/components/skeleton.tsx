import * as React from "react";

import { cn } from "../lib/cn";

export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden
      className={cn(
        "rounded-md bg-muted bg-[linear-gradient(90deg,transparent,rgba(255,255,255,0.35),transparent)] bg-[length:400px_100%] bg-no-repeat animate-[messer-shimmer_1.4s_linear_infinite] dark:bg-[linear-gradient(90deg,transparent,rgba(255,255,255,0.05),transparent)]",
        className,
      )}
      {...props}
    />
  );
}

export function SkeletonRows({ rows = 5, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("flex flex-col gap-2", className)} role="status" aria-label="Cargando">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-8 w-full" />
      ))}
    </div>
  );
}
