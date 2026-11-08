import type { ComponentPropsWithoutRef, ReactNode } from "react";
import { splitTwoTone } from "@/lib/text";

/** The 9px brand arrow used inside arrow-swap boxes and rail controls. */
export function Arrow({ className, style }: { className?: string; style?: React.CSSProperties }) {
  return (
    <svg
      aria-hidden="true"
      width="9"
      height="9"
      viewBox="0 0 10 10"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.1"
      className={className}
      style={style}
    >
      <path d="M1 5h8M5.5 1.5 9 5 5.5 8.5" />
    </svg>
  );
}

/** Square box whose diagonal arrow slides out and a twin slides in on hover/focus. */
export function ArrowBox({ size = "sm" }: { size?: "sm" | "lg" }) {
  return (
    <span className={size === "lg" ? "arrowbox arrowbox--lg" : "arrowbox"} aria-hidden="true">
      <span className="arrowbox__rot">
        <Arrow />
        <Arrow />
      </span>
    </span>
  );
}

type ButtonLinkProps = ComponentPropsWithoutRef<"a"> & { variant?: "solid" | "ghost"; arrow?: boolean };

/** Black (or signal "ghost") CTA link with the arrow-swap box. */
export function ButtonLink({ variant = "solid", arrow = true, className = "", children, ...rest }: ButtonLinkProps) {
  return (
    <a className={`btn ${variant === "ghost" ? "btn--ghost" : ""} ${className}`} {...rest}>
      {children}
      {arrow && <ArrowBox />}
    </a>
  );
}

/** Rust 6px square bullet. */
export function Square({ size = 6, className = "bg-rust" }: { size?: number; className?: string }) {
  return <span aria-hidden="true" className={`inline-block flex-none ${className}`} style={{ width: size, height: size }} />;
}

/** Mono uppercase eyebrow with a rust square. */
export function Eyebrow({ children, className = "", as: Tag = "span" }: { children: ReactNode; className?: string; as?: "span" | "h2" | "p" }) {
  return (
    <Tag
      className={`inline-flex items-center gap-2.5 font-mono text-[11px] font-normal uppercase tracking-[0.04em] ${className || "text-concrete"}`}
    >
      <Square />
      {children}
    </Tag>
  );
}

/**
 * H2 with the prototype's two-tone treatment: the last two words are muted
 * (skipped for zh and for headings under five words).
 */
export function TwoToneHeading({
  text,
  locale,
  as: Tag = "h2",
  className = "",
  mutedClassName = "text-concrete",
  id,
}: {
  text: string;
  locale: string;
  as?: "h2" | "h3";
  className?: string;
  mutedClassName?: string;
  id?: string;
}) {
  const { a, b } = splitTwoTone(text, locale);
  return (
    <Tag
      id={id}
      className={`m-0 text-[length:var(--fs-h2)] font-normal leading-[1.04] tracking-[-0.025em] text-balance ${className}`}
    >
      {a}
      {b && (
        <>
          {" "}
          <span className={mutedClassName}>{b}</span>
        </>
      )}
    </Tag>
  );
}

/** Section wrapper: full-bleed background, 1440px inner column, gutter padding. */
export function Section({
  id,
  className = "",
  innerClassName = "",
  children,
  reveal = true,
  labelledBy,
}: {
  id?: string;
  className?: string;
  innerClassName?: string;
  children: ReactNode;
  reveal?: boolean;
  labelledBy?: string;
}) {
  return (
    <section id={id} aria-labelledby={labelledBy} className={`gutter-x ${className}`}>
      <div className={`mx-auto max-w-[var(--container)] ${innerClassName}`} {...(reveal ? { "data-reveal": "" } : {})}>
        {children}
      </div>
    </section>
  );
}
