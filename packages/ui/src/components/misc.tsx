"use client";

import * as AvatarPrimitive from "@radix-ui/react-avatar";
import { Check, Copy } from "lucide-react";
import * as React from "react";
import { Toaster as SonnerToaster, toast } from "sonner";

import { cn } from "../lib/cn";
import { Button } from "./button";

export { toast };

export function Toaster() {
  return (
    <SonnerToaster
      position="bottom-right"
      toastOptions={{
        className: "!rounded-md !border !border-border !bg-surface !text-fg !text-sm !shadow-lg",
      }}
    />
  );
}

export function Kbd({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <kbd
      className={cn(
        "inline-flex h-5 min-w-5 items-center justify-center rounded-sm border border-border bg-subtle px-1 font-mono text-[11px] text-fg-muted",
        className,
      )}
    >
      {children}
    </kbd>
  );
}

export function Spinner({ className, label = "Cargando" }: { className?: string; label?: string }) {
  return (
    <span role="status" aria-label={label} className={cn("inline-block size-4 animate-spin rounded-full border-2 border-border-strong border-t-fg", className)} />
  );
}

export function Avatar({ name, src, className }: { name?: string | null; src?: string | null; className?: string }) {
  const initials = (name || "?")
    .split(/\s+|@/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("");
  return (
    <AvatarPrimitive.Root className={cn("inline-flex size-7 shrink-0 items-center justify-center overflow-hidden rounded-full bg-muted text-xs font-semibold text-fg-muted", className)}>
      {src ? <AvatarPrimitive.Image src={src} alt={name ?? ""} className="size-full object-cover" /> : null}
      <AvatarPrimitive.Fallback>{initials}</AvatarPrimitive.Fallback>
    </AvatarPrimitive.Root>
  );
}

export function PageHeader({
  title,
  description,
  actions,
  breadcrumbs,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  breadcrumbs?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-1 pb-5", className)}>
      {breadcrumbs ? <div className="text-xs text-fg-subtle">{breadcrumbs}</div> : null}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-lg font-semibold text-fg">{title}</h1>
          {description ? <p className="mt-1 max-w-3xl text-sm text-fg-muted">{description}</p> : null}
        </div>
        {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
    </div>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone,
  className,
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  hint?: React.ReactNode;
  tone?: "danger" | "success" | "warning";
  className?: string;
}) {
  return (
    <div className={cn("rounded-md border border-border bg-surface px-4 py-3", className)}>
      <p className="text-xs font-medium uppercase tracking-wide text-fg-subtle">{label}</p>
      <p
        className={cn(
          "tabular mt-1 text-lg font-semibold",
          tone === "danger" && "text-danger",
          tone === "success" && "text-success",
          tone === "warning" && "text-warning",
        )}
      >
        {value}
      </p>
      {hint ? <p className="mt-0.5 text-xs text-fg-muted">{hint}</p> : null}
    </div>
  );
}

export function CopyButton({ value, label = "Copiar", className }: { value: string; label?: string; className?: string }) {
  const [copied, setCopied] = React.useState(false);
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      className={className}
      aria-label={label}
      onClick={async () => {
        await navigator.clipboard.writeText(value);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      }}
    >
      {copied ? <Check /> : <Copy />}
    </Button>
  );
}

export function CodeBlock({ code, language, className }: { code: string; language?: string; className?: string }) {
  return (
    <div className={cn("group relative rounded-md border border-border bg-subtle", className)}>
      {language ? <div className="border-b border-border px-3 py-1 font-mono text-[11px] text-fg-subtle">{language}</div> : null}
      <pre className="overflow-x-auto p-3 font-mono text-xs leading-relaxed text-fg">
        <code>{code}</code>
      </pre>
      <div className="absolute right-1.5 top-1.5 opacity-0 transition-opacity group-hover:opacity-100">
        <CopyButton value={code} />
      </div>
    </div>
  );
}

export function Separator({ className }: { className?: string }) {
  return <div role="separator" className={cn("h-px w-full bg-border", className)} />;
}

export function Alert({
  tone = "info",
  title,
  children,
  action,
  className,
}: {
  tone?: "info" | "warning" | "danger" | "success" | "accent";
  title?: React.ReactNode;
  children?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  const tones = {
    info: "border-info/25 bg-info-soft",
    warning: "border-warning/25 bg-warning-soft",
    danger: "border-danger/25 bg-danger-soft",
    success: "border-success/25 bg-success-soft",
    accent: "border-accent/25 bg-accent-soft",
  } as const;
  return (
    <div role={tone === "danger" ? "alert" : "status"} className={cn("flex items-start justify-between gap-3 rounded-md border px-3 py-2.5 text-sm", tones[tone], className)}>
      <div className="min-w-0">
        {title ? <p className="font-semibold text-fg">{title}</p> : null}
        {children ? <div className="text-fg-muted">{children}</div> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}
