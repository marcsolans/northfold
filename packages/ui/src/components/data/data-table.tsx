"use client";

import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight } from "lucide-react";
import * as React from "react";

import { cn } from "../../lib/cn";
import { Badge } from "../badge";
import { Button } from "../button";
import { Input } from "../input";
import { Skeleton } from "../skeleton";
import { DataStatus, type DataStateLabels } from "./data-state";
import { type DataRow, type ValueFormat, columnsOf, formatValue, humanize, isNumericColumn, matchesSearch, toNumber } from "./format";

export interface DataTableColumn {
  key: string;
  label?: string | null;
  format?: ValueFormat;
  align?: "left" | "center" | "right" | null;
}

export interface DataTableLabels extends DataStateLabels {
  search: string;
  previous: string;
  next: string;
  page: (page: number, pages: number) => string;
  rows: (count: number) => string;
  sortBy: (column: string) => string;
  truncated: string;
}

export interface DataTableRowAction {
  label: string;
  onRun: (row: DataRow, index: number) => void | Promise<void>;
  busyRow?: number | null;
}

export interface DataTableProps {
  rows: DataRow[];
  columns?: DataTableColumn[];
  pageSize?: number;
  searchable?: boolean;
  loading?: boolean;
  error?: string | null;
  truncated?: boolean;
  emptyText?: string | null;
  onRetry?: () => void;
  rowAction?: DataTableRowAction | null;
  labels: DataTableLabels;
  locale?: string;
  currency?: string;
  caption?: string;
  className?: string;
}

function compare(a: unknown, b: unknown): number {
  const na = toNumber(a);
  const nb = toNumber(b);
  if (na !== null && nb !== null) return na - nb;
  if (a === null || a === undefined) return 1;
  if (b === null || b === undefined) return -1;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

/** Sortable, searchable, paginated table with formatted cells and an optional action per row. */
export function DataTable({
  rows,
  columns,
  pageSize = 10,
  searchable = false,
  loading,
  error,
  truncated,
  emptyText,
  onRetry,
  rowAction,
  labels,
  locale,
  currency,
  caption,
  className,
}: DataTableProps) {
  const [query, setQuery] = React.useState("");
  const [sort, setSort] = React.useState<{ key: string; dir: "asc" | "desc" } | null>(null);
  const [page, setPage] = React.useState(0);

  const cols = React.useMemo<DataTableColumn[]>(() => {
    if (columns && columns.length > 0) return columns;
    return columnsOf(rows).map((key) => ({ key, format: isNumericColumn(rows, key) ? "number" : "text" }));
  }, [columns, rows]);

  const visible = React.useMemo(() => {
    const keys = cols.map((c) => c.key);
    const filtered = searchable && query ? rows.filter((r) => matchesSearch(r, query, keys)) : rows;
    if (!sort) return filtered.map((row, index) => ({ row, index }));
    return filtered
      .map((row, index) => ({ row, index }))
      .sort((a, b) => (sort.dir === "asc" ? 1 : -1) * compare(a.row[sort.key], b.row[sort.key]));
  }, [rows, cols, query, searchable, sort]);

  const pages = Math.max(1, Math.ceil(visible.length / pageSize));
  const current = Math.min(page, pages - 1);
  const slice = visible.slice(current * pageSize, current * pageSize + pageSize);

  React.useEffect(() => setPage(0), [query, rows]);

  const toggleSort = (key: string) =>
    setSort((s) => (s?.key !== key ? { key, dir: "asc" } : s.dir === "asc" ? { key, dir: "desc" } : null));

  const align = (c: DataTableColumn) =>
    c.align ?? (c.format === "number" || c.format === "currency" || c.format === "percent" ? "right" : "left");

  return (
    <div className={cn("flex min-h-0 flex-1 flex-col gap-2", className)}>
      {searchable && !loading && !error && rows.length > 0 ? (
        <Input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={labels.search}
          aria-label={labels.search}
          className="max-w-xs"
        />
      ) : null}
      <DataStatus
        loading={loading}
        error={error}
        empty={!loading && !error && visible.length === 0}
        emptyText={emptyText}
        labels={labels}
        onRetry={onRetry}
        skeleton={
          <>
            <Skeleton className="h-8 w-full" />
            {Array.from({ length: Math.min(pageSize, 5) }, (_, i) => (
              <Skeleton key={i} className="h-7 w-full" />
            ))}
          </>
        }
      >
        <div className="min-h-0 flex-1 overflow-auto rounded-md border border-border">
          <table className="w-full border-collapse text-sm">
            {caption ? <caption className="sr-only">{caption}</caption> : null}
            <thead className="sticky top-0 z-[1] border-b border-border bg-subtle">
              <tr>
                {cols.map((c) => {
                  const label = c.label || humanize(c.key);
                  const active = sort?.key === c.key;
                  return (
                    <th
                      key={c.key}
                      scope="col"
                      aria-sort={active ? (sort?.dir === "asc" ? "ascending" : "descending") : "none"}
                      className={cn(
                        "h-8 whitespace-nowrap px-3 text-xs font-medium uppercase tracking-wide text-fg-subtle",
                        align(c) === "right" ? "text-right" : align(c) === "center" ? "text-center" : "text-left",
                      )}
                    >
                      <button
                        type="button"
                        onClick={() => toggleSort(c.key)}
                        aria-label={labels.sortBy(label)}
                        className="inline-flex items-center gap-1 hover:text-fg"
                      >
                        {label}
                        {active ? sort?.dir === "asc" ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" /> : null}
                      </button>
                    </th>
                  );
                })}
                {rowAction ? <th scope="col" className="w-px px-3" aria-label={rowAction.label} /> : null}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {slice.map(({ row, index }) => (
                <tr key={index} className="transition-colors hover:bg-subtle/60">
                  {cols.map((c) => {
                    const value = row[c.key];
                    const text = formatValue(value, c.format, { locale, currency });
                    return (
                      <td
                        key={c.key}
                        className={cn(
                          "max-w-80 truncate px-3 py-1.5 align-middle text-fg",
                          align(c) === "right" ? "tabular text-right" : align(c) === "center" ? "text-center" : "",
                        )}
                        title={text.length > 40 ? text : undefined}
                      >
                        {c.format === "badge" && value !== null && value !== undefined && value !== "" ? (
                          <Badge>{text}</Badge>
                        ) : (
                          text
                        )}
                      </td>
                    );
                  })}
                  {rowAction ? (
                    <td className="whitespace-nowrap px-3 py-1 text-right">
                      <Button
                        size="sm"
                        variant="secondary"
                        loading={rowAction.busyRow === index}
                        disabled={rowAction.busyRow !== null && rowAction.busyRow !== undefined}
                        onClick={() => void rowAction.onRun(row, index)}
                      >
                        {rowAction.label}
                      </Button>
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-fg-subtle">
          <span className="tabular">
            {labels.rows(visible.length)}
            {truncated ? ` · ${labels.truncated}` : ""}
          </span>
          {pages > 1 ? (
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={labels.previous}
                disabled={current === 0}
                onClick={() => setPage(current - 1)}
              >
                <ChevronLeft />
              </Button>
              <span className="tabular">{labels.page(current + 1, pages)}</span>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={labels.next}
                disabled={current >= pages - 1}
                onClick={() => setPage(current + 1)}
              >
                <ChevronRight />
              </Button>
            </div>
          ) : null}
        </div>
      </DataStatus>
    </div>
  );
}
