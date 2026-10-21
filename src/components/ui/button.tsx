import { type ButtonHTMLAttributes, type ReactNode } from "react";

import { cn } from "@/lib/utils";

import { Spinner } from "./spinner";

export type ButtonVariant =
  "primary" | "accent" | "secondary" | "outline" | "ghost" | "destructive" | "link";
export type ButtonSize = "sm" | "md" | "lg" | "icon";

const base =
  "inline-flex items-center justify-center gap-2 rounded-md font-medium tracking-wide whitespace-nowrap transition-colors duration-200 select-none disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

const variants: Record<ButtonVariant, string> = {
  primary: "bg-primary text-primary-foreground hover:bg-primary/85",
  accent: "bg-accent text-accent-foreground hover:bg-accent/90",
  secondary: "bg-surface text-foreground hover:bg-border",
  outline: "border border-input bg-card text-foreground hover:border-foreground",
  ghost: "text-foreground hover:bg-surface",
  destructive: "bg-destructive text-destructive-foreground hover:bg-destructive/90",
  link: "text-foreground underline-offset-4 hover:underline px-0",
};

const sizes: Record<ButtonSize, string> = {
  sm: "h-9 px-3 text-sm",
  md: "h-11 px-5 text-sm",
  lg: "h-12 px-7 text-base",
  icon: "size-10",
};

/** Class names for a button-styled element (used by links that look like buttons). */
export function buttonClasses({
  variant = "primary",
  size = "md",
  className,
}: {
  variant?: ButtonVariant;
  size?: ButtonSize;
  className?: string;
} = {}): string {
  return cn(base, variants[variant], sizes[size], className);
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Shows a spinner and disables the button while an action is running. */
  loading?: boolean;
  loadingText?: ReactNode;
}

export function Button({
  variant,
  size,
  loading = false,
  loadingText,
  disabled,
  className,
  children,
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={buttonClasses({ variant, size, className })}
      {...props}
    >
      {loading ? <Spinner /> : null}
      {loading && loadingText ? loadingText : children}
    </button>
  );
}
