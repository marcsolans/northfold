import Link from "next/link";

import { STORE } from "@/lib/store-config";
import { cn } from "@/lib/utils";

/** Wordmark with a small folded-corner mark. */
export function Logo({ className, href = "/" }: { className?: string; href?: string }) {
  return (
    <Link
      href={href}
      className={cn("inline-flex items-center gap-2.5 text-foreground", className)}
      aria-label={`${STORE.name} — home`}
    >
      <svg aria-hidden="true" viewBox="0 0 24 24" className="size-6 shrink-0">
        <path d="M4 4h11l5 5v11H4z" fill="currentColor" />
        <path d="M15 4v5h5z" fill="var(--color-accent)" />
      </svg>
      <span className="text-[0.95rem] font-medium tracking-[0.28em] uppercase">{STORE.name}</span>
    </Link>
  );
}
