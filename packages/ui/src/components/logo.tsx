import { cn } from "../lib/cn";

/** Messer wordmark: a red square with a white diagonal blade, and the name. */
export function Logo({ className, compact = false }: { className?: string; compact?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2 font-semibold tracking-tight text-fg", className)}>
      <svg viewBox="0 0 16 16" className="size-4" aria-hidden>
        <rect width="16" height="16" rx="2" fill="#D52B1E" />
        <path d="M3.5 12.5 10.5 3.5h2l-7 9z" fill="#fff" />
      </svg>
      {compact ? null : <span className="text-md">Messer</span>}
    </span>
  );
}
