import { type Ref, type SelectHTMLAttributes } from "react";
import { HiChevronDown } from "react-icons/hi2";

import { cn } from "@/lib/utils";

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export function Select({
  options,
  placeholder,
  className,
  ref,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & {
  options: readonly SelectOption[];
  placeholder?: string;
  ref?: Ref<HTMLSelectElement>;
}) {
  return (
    <div className={cn("relative", className)}>
      <select
        ref={ref}
        className="h-11 w-full appearance-none rounded-md border border-input bg-card pr-10 pl-3.5 text-sm text-foreground transition-colors focus-visible:border-foreground focus-visible:ring-2 focus-visible:ring-accent/30 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-60 aria-invalid:border-destructive"
        {...props}
      >
        {placeholder ? <option value="">{placeholder}</option> : null}
        {options.map((option) => (
          <option key={option.value} value={option.value} disabled={option.disabled}>
            {option.label}
          </option>
        ))}
      </select>
      <HiChevronDown
        aria-hidden="true"
        className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted-foreground"
      />
    </div>
  );
}
