"use client";

import { CopyButton, cn } from "@messer/ui";
import { ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

type JsonValue = unknown;

function isContainer(value: JsonValue): value is Record<string, unknown> | unknown[] {
  return value !== null && typeof value === "object";
}

function Scalar({ value }: { value: JsonValue }) {
  if (value === null || value === undefined) return <span className="text-fg-subtle">null</span>;
  if (typeof value === "string") {
    return <span className="whitespace-pre-wrap break-words text-success">&quot;{value}&quot;</span>;
  }
  if (typeof value === "number") return <span className="tabular text-info">{String(value)}</span>;
  if (typeof value === "boolean") return <span className="text-warning">{String(value)}</span>;
  return <span>{String(value)}</span>;
}

function Node({
  name,
  value,
  depth,
  defaultDepth,
}: {
  name: string | null;
  value: JsonValue;
  depth: number;
  defaultDepth: number;
}) {
  const t = useTranslations("traces.json");
  const [open, setOpen] = React.useState(depth < defaultDepth);
  const label = name !== null ? <span className="text-fg-muted">{name}: </span> : null;
  if (!isContainer(value)) {
    return (
      <div className="pl-4">
        {label}
        <Scalar value={value} />
      </div>
    );
  }
  const entries: [string, unknown][] = Array.isArray(value)
    ? value.map((v, i) => [String(i), v])
    : Object.entries(value);
  const brackets = Array.isArray(value) ? ["[", "]"] : ["{", "}"];
  if (entries.length === 0) {
    return (
      <div className="pl-4">
        {label}
        <span className="text-fg-subtle">{brackets.join("")}</span>
      </div>
    );
  }
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex items-center gap-0.5 rounded-sm text-left hover:bg-muted"
      >
        <ChevronRight className={cn("size-3.5 shrink-0 text-fg-subtle transition-transform", open && "rotate-90")} aria-hidden />
        {label}
        <span className="text-fg-subtle">
          {brackets[0]}
          {open ? "" : ` ${t("items", { count: entries.length })} ${brackets[1]}`}
        </span>
      </button>
      {open ? (
        <div className="ml-[7px] border-l border-border pl-1">
          {entries.map(([k, v]) => (
            <Node key={k} name={Array.isArray(value) ? null : k} value={v} depth={depth + 1} defaultDepth={defaultDepth} />
          ))}
        </div>
      ) : null}
      {open ? <div className="pl-4 text-fg-subtle">{brackets[1]}</div> : null}
    </div>
  );
}

/** Collapsible JSON viewer with copy. */
export function JsonView({
  value,
  defaultDepth = 2,
  className,
  emptyLabel,
}: {
  value: JsonValue;
  defaultDepth?: number;
  className?: string;
  emptyLabel?: string;
}) {
  const t = useTranslations("traces.json");
  const text = React.useMemo(() => {
    if (typeof value === "string") return value;
    try {
      return JSON.stringify(value, null, 2) ?? "";
    } catch {
      return String(value);
    }
  }, [value]);
  if (value === undefined || value === null || (typeof value === "string" && value === "")) {
    return <p className={cn("text-xs text-fg-subtle", className)}>{emptyLabel ?? t("empty")}</p>;
  }
  return (
    <div className={cn("group relative rounded-md border border-border bg-subtle", className)}>
      <div className="absolute right-1 top-1 opacity-60 transition-opacity group-hover:opacity-100">
        <CopyButton value={text} label={t("copy")} />
      </div>
      <div className="max-h-[28rem] overflow-auto p-2.5 pr-9 font-mono text-xs leading-relaxed">
        {typeof value === "string" ? (
          <pre className="whitespace-pre-wrap break-words">{value}</pre>
        ) : (
          <div className="-ml-4">
            <Node name={null} value={value} depth={0} defaultDepth={defaultDepth} />
          </div>
        )}
      </div>
    </div>
  );
}
