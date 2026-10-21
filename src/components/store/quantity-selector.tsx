"use client";

import { HiMinus, HiPlus } from "react-icons/hi2";

import { cn } from "@/lib/utils";

export function QuantitySelector({
  value,
  max,
  onChange,
  disabled = false,
  label = "Quantity",
  size = "md",
}: {
  value: number;
  max: number;
  onChange: (value: number) => void;
  disabled?: boolean;
  label?: string;
  size?: "sm" | "md";
}) {
  const buttonClass = cn(
    "inline-flex items-center justify-center text-foreground transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-40",
    size === "sm" ? "size-8" : "size-11",
  );
  return (
    <div
      role="group"
      aria-label={label}
      className={cn(
        "inline-flex items-center rounded-md border border-input bg-card",
        disabled && "opacity-60",
      )}
    >
      <button
        type="button"
        className={buttonClass}
        onClick={() => onChange(value - 1)}
        disabled={disabled || value <= 1}
        aria-label="Decrease quantity"
      >
        <HiMinus aria-hidden="true" className="size-4" />
      </button>
      <output
        aria-live="polite"
        className={cn("text-center text-sm tabular-nums", size === "sm" ? "w-7" : "w-10")}
      >
        {value}
      </output>
      <button
        type="button"
        className={buttonClass}
        onClick={() => onChange(value + 1)}
        disabled={disabled || value >= max}
        aria-label="Increase quantity"
      >
        <HiPlus aria-hidden="true" className="size-4" />
      </button>
    </div>
  );
}
