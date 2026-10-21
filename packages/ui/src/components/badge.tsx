import { type VariantProps, cva } from "class-variance-authority";
import * as React from "react";

import { cn } from "../lib/cn";

export const badgeVariants = cva(
  "inline-flex items-center gap-1 whitespace-nowrap rounded-sm border px-1.5 py-px text-xs font-medium",
  {
    variants: {
      tone: {
        neutral: "border-border bg-subtle text-fg-muted",
        accent: "border-accent/25 bg-accent-soft text-accent",
        success: "border-success/25 bg-success-soft text-success",
        warning: "border-warning/25 bg-warning-soft text-warning",
        danger: "border-danger/25 bg-danger-soft text-danger",
        info: "border-info/25 bg-info-soft text-info",
        outline: "border-border bg-transparent text-fg-muted",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

export type StatusTone = "neutral" | "success" | "warning" | "danger" | "info" | "accent";

export function StatusDot({ tone = "neutral", pulse = false, className }: { tone?: StatusTone; pulse?: boolean; className?: string }) {
  const color = {
    neutral: "bg-fg-subtle",
    success: "bg-success",
    warning: "bg-warning",
    danger: "bg-danger",
    info: "bg-info",
    accent: "bg-accent",
  }[tone];
  return (
    <span
      aria-hidden
      className={cn("inline-block size-2 rounded-full", color, pulse && "animate-[messer-pulse-dot_1.4s_ease-in-out_infinite]", className)}
    />
  );
}
