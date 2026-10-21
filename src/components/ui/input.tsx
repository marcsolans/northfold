import { type InputHTMLAttributes, type Ref, type TextareaHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

const control =
  "w-full rounded-md border border-input bg-card px-3.5 text-sm text-foreground placeholder:text-muted-foreground/80 transition-colors focus-visible:border-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/30 disabled:cursor-not-allowed disabled:opacity-60 aria-invalid:border-destructive aria-invalid:ring-destructive/20";

export function Input({
  className,
  ref,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { ref?: Ref<HTMLInputElement> }) {
  return <input ref={ref} className={cn(control, "h-11", className)} {...props} />;
}

export function Textarea({
  className,
  ref,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement> & { ref?: Ref<HTMLTextAreaElement> }) {
  return <textarea ref={ref} className={cn(control, "min-h-28 py-2.5", className)} {...props} />;
}
