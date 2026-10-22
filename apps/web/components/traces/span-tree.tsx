"use client";

import { Badge, cn } from "@messer/ui";
import { ChevronRight } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { formatDuration, formatUsd, localeTag } from "@/lib/format";
import { formatTokens, toNumber } from "@/lib/studio/format";
import type { Span } from "@/lib/studio/types";

export interface SpanRow {
  span: Span;
  depth: number;
  hasChildren: boolean;
}

interface SpanNode {
  span: Span;
  children: SpanNode[];
}

export function buildSpanTree(spans: Span[]): SpanNode[] {
  const byId = new Map<string, SpanNode>();
  for (const span of spans) byId.set(span.id, { span, children: [] });
  const roots: SpanNode[] = [];
  for (const node of byId.values()) {
    const parent = node.span.parent_span_id ? byId.get(node.span.parent_span_id) : undefined;
    if (parent && parent !== node) parent.children.push(node);
    else roots.push(node);
  }
  const sort = (nodes: SpanNode[]) => {
    nodes.sort((a, b) => a.span.t0 - b.span.t0);
    nodes.forEach((n) => sort(n.children));
  };
  sort(roots);
  return roots;
}

function flatten(nodes: SpanNode[], collapsed: Set<string>, depth = 0, out: SpanRow[] = []): SpanRow[] {
  for (const node of nodes) {
    out.push({ span: node.span, depth, hasChildren: node.children.length > 0 });
    if (!collapsed.has(node.span.id)) flatten(node.children, collapsed, depth + 1, out);
  }
  return out;
}

export function spanRange(spans: Span[]): { start: number; end: number } {
  if (spans.length === 0) return { start: 0, end: 1 };
  const start = Math.min(...spans.map((s) => s.t0));
  const end = Math.max(...spans.map((s) => s.t1 ?? s.t0));
  return { start, end: Math.max(end, start + 1) };
}

export function spanDuration(span: Span): number | null {
  return span.t1 !== null ? Math.max(0, span.t1 - span.t0) : null;
}

const KIND_BAR: Record<string, string> = {
  agent: "bg-fg/70",
  workflow: "bg-fg/70",
  step: "bg-success",
  llm: "bg-info",
  tool: "bg-accent",
  guardrail: "bg-warning",
  guard: "bg-warning",
};

export function useSpanKindLabel() {
  const t = useTranslations("traces.kinds");
  return (kind: string) => (t.has(kind) ? t(kind) : kind);
}

/** Span tree with one waterfall bar per span (t0 → t1 relative to the run). */
export function SpanTree({
  spans,
  selectedId,
  onSelect,
}: {
  spans: Span[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const t = useTranslations("traces.detail");
  const locale = localeTag(useLocale());
  const kindLabel = useSpanKindLabel();
  const [collapsed, setCollapsed] = React.useState<Set<string>>(new Set());
  const tree = React.useMemo(() => buildSpanTree(spans), [spans]);
  const rows = React.useMemo(() => flatten(tree, collapsed), [tree, collapsed]);
  const { start, end } = React.useMemo(() => spanRange(spans), [spans]);
  const total = end - start;

  const toggle = (id: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="min-w-0">
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(8rem,40%)] border-b border-border bg-subtle px-3 py-1.5 text-[11px] font-medium uppercase tracking-wide text-fg-subtle">
        <span>{t("span")}</span>
        <span className="flex justify-between">
          <span>0</span>
          <span className="tabular">{formatDuration(total)}</span>
        </span>
      </div>
      <ul role="tree" aria-label={t("spanTree")} className="divide-y divide-border">
        {rows.map(({ span, depth, hasChildren }) => {
          const duration = spanDuration(span);
          const left = ((span.t0 - start) / total) * 100;
          const width = Math.max(((duration ?? 0) / total) * 100, 0.6);
          const failed = span.status === "error" || Boolean(span.error);
          const selected = span.id === selectedId;
          const tokens = span.input_tokens + span.output_tokens;
          return (
            <li
              key={span.id}
              role="treeitem"
              aria-level={depth + 1}
              aria-selected={selected}
              aria-expanded={hasChildren ? !collapsed.has(span.id) : undefined}
              className={cn("grid grid-cols-[minmax(0,1fr)_minmax(8rem,40%)] items-center", selected ? "bg-accent-soft/50" : "hover:bg-subtle")}
            >
              <div className="flex min-w-0 items-center gap-1 py-1.5 pr-2" style={{ paddingLeft: `${0.5 + depth * 0.9}rem` }}>
                {hasChildren ? (
                  <button
                    type="button"
                    className="rounded-sm p-0.5 hover:bg-muted"
                    aria-label={collapsed.has(span.id) ? t("expand", { name: span.name }) : t("collapse", { name: span.name })}
                    onClick={() => toggle(span.id)}
                  >
                    <ChevronRight className={cn("size-3.5 transition-transform", !collapsed.has(span.id) && "rotate-90")} />
                  </button>
                ) : (
                  <span className="w-[1.125rem]" aria-hidden />
                )}
                <button type="button" onClick={() => onSelect(span.id)} className="flex min-w-0 flex-1 items-center gap-2 text-left">
                  <Badge tone={failed ? "danger" : "outline"} className="shrink-0 px-1 text-[10px] uppercase">
                    {kindLabel(span.kind)}
                  </Badge>
                  <span className="truncate font-mono text-xs">{span.name}</span>
                  <span className="ml-auto flex shrink-0 items-center gap-2 text-[11px] text-fg-subtle">
                    {tokens > 0 ? <span className="tabular hidden xl:inline">{t("tokensShort", { value: formatTokens(tokens, locale) })}</span> : null}
                    {toNumber(span.cost_usd) > 0 ? <span className="tabular hidden lg:inline">{formatUsd(span.cost_usd, locale)}</span> : null}
                    <span className="tabular">{formatDuration(duration)}</span>
                  </span>
                </button>
              </div>
              <div className="relative h-full min-h-7 border-l border-border" aria-hidden>
                <span
                  className={cn("absolute top-1/2 h-2 -translate-y-1/2 rounded-sm", failed ? "bg-danger" : (KIND_BAR[span.kind] ?? "bg-fg-subtle"))}
                  style={{ left: `${Math.min(left, 99.4)}%`, width: `${Math.min(width, 100 - Math.min(left, 99.4))}%` }}
                />
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
