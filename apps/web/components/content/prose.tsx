import { CopyButton, cn } from "@messer/ui";
import { Info, Link2, TriangleAlert } from "lucide-react";
import Link from "next/link";
import * as React from "react";

/**
 * Typography for rendered Markdown/MDX (docs, blog, legal). Server components only, tokens for dark mode.
 * MDX passes HTML attributes as props; only the ones we render are typed here.
 */

type WithChildren = { children?: React.ReactNode; className?: string; id?: string };

const SAFE_URL = /^(https?:|mailto:|\/(?!\/)|#|\.{0,2}\/?[\w-])/i;

export interface ProseLabels {
  copy: string;
  plainText: string;
  anchor: string;
}

function Heading({
  level,
  id,
  children,
  anchorLabel,
}: {
  level: 2 | 3 | 4;
  id?: string;
  children?: React.ReactNode;
  anchorLabel: string;
}) {
  const Tag = `h${level}` as const;
  const styles = {
    2: "mt-10 mb-3 text-lg font-semibold tracking-tight text-fg",
    3: "mt-8 mb-2 text-md font-semibold text-fg",
    4: "mt-6 mb-2 text-base font-semibold text-fg",
  }[level];
  return (
    <Tag id={id} className={cn("group scroll-mt-24", styles)}>
      {children}
      {id ? (
        <a
          href={`#${id}`}
          className="ml-2 inline-flex align-middle text-fg-subtle opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
          aria-label={anchorLabel}
        >
          <Link2 className="size-3.5" aria-hidden />
        </a>
      ) : null}
    </Tag>
  );
}

function Anchor({ href, children, title }: { href?: string; children?: React.ReactNode; title?: string }) {
  const className = "font-medium text-fg underline decoration-border-strong underline-offset-4 hover:decoration-fg";
  if (!href || !SAFE_URL.test(href)) return <span>{children}</span>;
  if (href.startsWith("/") || href.startsWith("#")) {
    return (
      <Link href={href} className={className} title={title}>
        {children}
      </Link>
    );
  }
  const external = /^https?:/i.test(href);
  return (
    <a
      href={href}
      title={title}
      className={className}
      {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}
    >
      {children}
    </a>
  );
}

function codeText(node: React.ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(codeText).join("");
  if (React.isValidElement<{ children?: React.ReactNode }>(node)) return codeText(node.props.children);
  return "";
}

function Pre({ children, labels }: { children?: React.ReactNode; labels: ProseLabels }) {
  const child = React.isValidElement<{ className?: string; children?: React.ReactNode }>(children) ? children : null;
  const language = child?.props.className?.match(/language-([\w+-]+)/)?.[1];
  const code = codeText(child ? child.props.children : children).replace(/\n$/, "");
  return (
    <figure className="group relative my-5 overflow-hidden rounded-md border border-border bg-subtle">
      <div className="flex h-8 items-center justify-between border-b border-border px-3">
        <span className="font-mono text-[11px] uppercase tracking-wide text-fg-subtle">{language ?? labels.plainText}</span>
        <CopyButton value={code} label={labels.copy} className="-mr-2" />
      </div>
      <pre className="overflow-x-auto p-3 font-mono text-[12.5px] leading-relaxed text-fg">
        <code>{code}</code>
      </pre>
    </figure>
  );
}

function InlineCode({ children }: WithChildren) {
  return (
    <code className="rounded-sm border border-border bg-subtle px-1 py-px font-mono text-[0.9em] text-fg">{children}</code>
  );
}

function Blockquote({ children }: WithChildren) {
  return (
    <blockquote className="my-5 rounded-md border border-border border-l-2 border-l-accent bg-subtle px-4 py-3 text-fg-muted [&>p:first-child]:mt-0 [&>p:last-child]:mb-0">
      {children}
    </blockquote>
  );
}

/** `<Callout tone="warning" title="…">` in MDX posts. */
export function Callout({
  tone = "info",
  title,
  children,
}: {
  tone?: "info" | "warning";
  title?: string;
  children?: React.ReactNode;
}) {
  const Icon = tone === "warning" ? TriangleAlert : Info;
  return (
    <aside
      className={cn(
        "my-5 flex gap-3 rounded-md border px-4 py-3 text-sm",
        tone === "warning" ? "border-warning/25 bg-warning-soft" : "border-info/25 bg-info-soft",
      )}
    >
      <Icon className={cn("mt-0.5 size-4 shrink-0", tone === "warning" ? "text-warning" : "text-info")} aria-hidden />
      <div className="min-w-0 text-fg-muted [&>p]:my-1">
        {title ? <p className="font-semibold text-fg">{title}</p> : null}
        {children}
      </div>
    </aside>
  );
}

export function proseComponents(labels: ProseLabels) {
  return {
    h1: ({ children, id }: WithChildren) => (
      <h2 id={id} className="mt-10 mb-3 scroll-mt-24 text-lg font-semibold tracking-tight">
        {children}
      </h2>
    ),
    h2: ({ children, id }: WithChildren) => (
      <Heading level={2} id={id} anchorLabel={labels.anchor}>
        {children}
      </Heading>
    ),
    h3: ({ children, id }: WithChildren) => (
      <Heading level={3} id={id} anchorLabel={labels.anchor}>
        {children}
      </Heading>
    ),
    h4: ({ children, id }: WithChildren) => (
      <Heading level={4} id={id} anchorLabel={labels.anchor}>
        {children}
      </Heading>
    ),
    p: ({ children }: WithChildren) => <p className="my-4 leading-7 text-fg-muted">{children}</p>,
    a: Anchor,
    strong: ({ children }: WithChildren) => <strong className="font-semibold text-fg">{children}</strong>,
    em: ({ children }: WithChildren) => <em className="italic">{children}</em>,
    ul: ({ children }: WithChildren) => (
      <ul className="my-4 list-disc space-y-1.5 pl-5 leading-7 text-fg-muted marker:text-fg-subtle">{children}</ul>
    ),
    ol: ({ children }: WithChildren) => (
      <ol className="my-4 list-decimal space-y-1.5 pl-5 leading-7 text-fg-muted marker:text-fg-subtle">{children}</ol>
    ),
    li: ({ children }: WithChildren) => <li className="pl-1 [&>p]:my-1">{children}</li>,
    blockquote: Blockquote,
    hr: () => <hr className="my-8 border-border" />,
    pre: ({ children }: WithChildren) => <Pre labels={labels}>{children}</Pre>,
    code: InlineCode,
    table: ({ children }: WithChildren) => (
      <div className="my-5 overflow-x-auto rounded-md border border-border">
        <table className="w-full border-collapse text-left text-sm">{children}</table>
      </div>
    ),
    thead: ({ children }: WithChildren) => <thead className="bg-subtle">{children}</thead>,
    th: ({ children }: WithChildren) => (
      <th className="border-b border-border px-3 py-2 text-xs font-semibold uppercase tracking-wide text-fg-subtle">
        {children}
      </th>
    ),
    td: ({ children }: WithChildren) => (
      <td className="border-b border-border px-3 py-2 align-top text-fg-muted [tr:last-child_&]:border-b-0">{children}</td>
    ),
    img: ({ src, alt }: { src?: string; alt?: string }) =>
      src && SAFE_URL.test(src) ? (
        // Markdown images have no intrinsic size; they are lazy-loaded and constrained to the column.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={src} alt={alt ?? ""} loading="lazy" decoding="async" className="my-5 h-auto max-w-full rounded-md border border-border" />
      ) : null,
    Callout,
  };
}
