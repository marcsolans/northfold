import { type InputHTMLAttributes, type ReactNode, type Ref, useId } from "react";

import { cn } from "@/lib/utils";

export function Checkbox({
  label,
  description,
  className,
  id,
  ref,
  ...props
}: Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & {
  label: ReactNode;
  description?: ReactNode;
  ref?: Ref<HTMLInputElement>;
}) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  return (
    <div className={cn("flex items-start gap-3", className)}>
      <input
        ref={ref}
        id={inputId}
        type="checkbox"
        className="mt-0.5 size-4 shrink-0 cursor-pointer rounded-sm border-input accent-accent"
        {...props}
      />
      <div className="text-sm leading-tight">
        <label htmlFor={inputId} className="cursor-pointer font-medium text-foreground">
          {label}
        </label>
        {description ? <p className="mt-1 text-muted-foreground">{description}</p> : null}
      </div>
    </div>
  );
}
