import Link from "next/link";
import { type ReactNode } from "react";
import { HiArrowRight } from "react-icons/hi2";

export function SectionHeading({
  eyebrow,
  title,
  href,
  linkLabel,
  id,
}: {
  eyebrow?: string;
  title: ReactNode;
  href?: string;
  linkLabel?: string;
  id?: string;
}) {
  return (
    <div className="mb-8 flex items-end justify-between gap-6">
      <div>
        {eyebrow ? (
          <p className="text-xs font-medium tracking-[0.25em] text-accent uppercase">{eyebrow}</p>
        ) : null}
        <h2 id={id} className="mt-2 text-2xl font-light tracking-tight sm:text-3xl">
          {title}
        </h2>
      </div>
      {href && linkLabel ? (
        <Link
          href={href}
          className="group inline-flex shrink-0 items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          {linkLabel}
          <HiArrowRight
            aria-hidden="true"
            className="size-4 transition-transform group-hover:translate-x-0.5"
          />
        </Link>
      ) : null}
    </div>
  );
}
