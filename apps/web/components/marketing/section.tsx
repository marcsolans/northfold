import { cn } from "@messer/ui";
import { ChevronDown } from "lucide-react";
import type * as React from "react";

export function Container({ className, children }: { className?: string; children: React.ReactNode }) {
  return <div className={cn("mx-auto w-full max-w-6xl px-4 sm:px-6", className)}>{children}</div>;
}

export function Section({
  id,
  className,
  children,
  tone = "default",
  labelledBy,
}: {
  id?: string;
  className?: string;
  children: React.ReactNode;
  tone?: "default" | "subtle";
  labelledBy?: string;
}) {
  return (
    <section
      id={id}
      aria-labelledby={labelledBy}
      className={cn("scroll-mt-16 border-t border-border py-16 sm:py-20", tone === "subtle" && "bg-subtle", className)}
    >
      <Container>{children}</Container>
    </section>
  );
}

export function SectionHeader({
  id,
  eyebrow,
  title,
  subtitle,
  className,
  as: Tag = "h2",
}: {
  id?: string;
  eyebrow?: string;
  title: string;
  subtitle?: string;
  className?: string;
  as?: "h1" | "h2";
}) {
  return (
    <div className={cn("max-w-3xl", className)}>
      {eyebrow ? <p className="text-xs font-semibold uppercase tracking-wide text-accent">{eyebrow}</p> : null}
      <Tag
        id={id}
        className={cn(
          "mt-2 font-semibold tracking-tight text-fg",
          Tag === "h1" ? "text-xl leading-tight sm:text-2xl" : "text-lg leading-snug sm:text-xl",
        )}
      >
        {title}
      </Tag>
      {subtitle ? <p className="mt-3 text-md leading-relaxed text-fg-muted">{subtitle}</p> : null}
    </div>
  );
}

/** Accessible FAQ built on <details>: works without JavaScript. */
export function Faq({ items, className }: { items: { q: string; a: string }[]; className?: string }) {
  return (
    <div className={cn("divide-y divide-border rounded-md border border-border bg-surface", className)}>
      {items.map((item) => (
        <details key={item.q} className="group px-4 [&_summary::-webkit-details-marker]:hidden">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-4 py-4 text-base font-medium text-fg">
            {item.q}
            <ChevronDown
              className="size-4 shrink-0 text-fg-subtle transition-transform group-open:rotate-180"
              aria-hidden
            />
          </summary>
          <p className="-mt-1 pb-4 text-sm leading-relaxed text-fg-muted">{item.a}</p>
        </details>
      ))}
    </div>
  );
}

/** JSON-LD structured data. Data blocks are not executed, so the strict CSP does not apply to them. */
export function JsonLd({ data }: { data: Record<string, unknown> | Record<string, unknown>[] }) {
  const json = JSON.stringify(data).replace(/</g, "\\u003c");
  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: json }} />;
}
