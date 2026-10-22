"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import * as React from "react";

import { cn } from "../../lib/cn";
import { Badge } from "../badge";
import { Button } from "../button";
import { Input } from "../input";
import { Skeleton } from "../skeleton";
import { DataStatus, type DataStateLabels } from "./data-state";
import { type DataRow, columnsOf, formatValue, humanize, matchesSearch } from "./format";

export interface RecordListLabels extends DataStateLabels {
  search: string;
  previous: string;
  next: string;
  page: (page: number, pages: number) => string;
}

/** Compact list of records: a title, a subtitle, a few meta fields and a badge per item. */
export function RecordList({
  rows,
  titleField,
  subtitleField,
  metaFields = [],
  badgeField,
  pageSize = 10,
  searchable = false,
  loading,
  error,
  emptyText,
  onRetry,
  rowAction,
  labels,
  locale,
  className,
}: {
  rows: DataRow[];
  titleField?: string | null;
  subtitleField?: string | null;
  metaFields?: string[];
  badgeField?: string | null;
  pageSize?: number;
  searchable?: boolean;
  loading?: boolean;
  error?: string | null;
  emptyText?: string | null;
  onRetry?: () => void;
  rowAction?: { label: string; onRun: (row: DataRow, index: number) => void | Promise<void>; busyRow?: number | null } | null;
  labels: RecordListLabels;
  locale?: string;
  className?: string;
}) {
  const [query, setQuery] = React.useState("");
  const [page, setPage] = React.useState(0);
  const columns = React.useMemo(() => columnsOf(rows), [rows]);
  const title = titleField || columns[0] || "";
  const subtitle = subtitleField ?? (columns[1] && columns[1] !== title ? columns[1] : null);
  const visible = React.useMemo(() => {
    const items = rows.map((row, index) => ({ row, index }));
    return searchable && query ? items.filter((i) => matchesSearch(i.row, query, columns)) : items;
  }, [rows, searchable, query, columns]);
  const pages = Math.max(1, Math.ceil(visible.length / pageSize));
  const current = Math.min(page, pages - 1);
  React.useEffect(() => setPage(0), [query, rows]);

  return (
    <div className={cn("flex min-h-0 flex-1 flex-col gap-2", className)}>
      {searchable && !loading && !error && rows.length > 0 ? (
        <Input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={labels.search} aria-label={labels.search} />
      ) : null}
      <DataStatus
        loading={loading}
        error={error}
        empty={!loading && !error && visible.length === 0}
        emptyText={emptyText}
        labels={labels}
        onRetry={onRetry}
        skeleton={Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      >
        <ul className="flex min-h-0 flex-1 flex-col divide-y divide-border overflow-auto rounded-md border border-border">
          {visible.slice(current * pageSize, current * pageSize + pageSize).map(({ row, index }) => (
            <li key={index} className="flex items-center gap-3 px-3 py-2">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-fg">{formatValue(row[title], "text", { locale })}</p>
                {subtitle ? <p className="truncate text-xs text-fg-muted">{formatValue(row[subtitle], "text", { locale })}</p> : null}
                {metaFields.length > 0 ? (
                  <p className="mt-0.5 flex flex-wrap gap-x-3 text-xs text-fg-subtle">
                    {metaFields.map((m) => (
                      <span key={m}>
                        {humanize(m)}: <span className="text-fg-muted">{formatValue(row[m], "text", { locale })}</span>
                      </span>
                    ))}
                  </p>
                ) : null}
              </div>
              {badgeField && row[badgeField] !== null && row[badgeField] !== undefined && row[badgeField] !== "" ? (
                <Badge>{formatValue(row[badgeField], "text", { locale })}</Badge>
              ) : null}
              {rowAction ? (
                <Button
                  size="sm"
                  variant="secondary"
                  loading={rowAction.busyRow === index}
                  disabled={rowAction.busyRow !== null && rowAction.busyRow !== undefined}
                  onClick={() => void rowAction.onRun(row, index)}
                >
                  {rowAction.label}
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
        {pages > 1 ? (
          <div className="flex items-center justify-end gap-1 text-xs text-fg-subtle">
            <Button variant="ghost" size="icon-sm" aria-label={labels.previous} disabled={current === 0} onClick={() => setPage(current - 1)}>
              <ChevronLeft />
            </Button>
            <span className="tabular">{labels.page(current + 1, pages)}</span>
            <Button variant="ghost" size="icon-sm" aria-label={labels.next} disabled={current >= pages - 1} onClick={() => setPage(current + 1)}>
              <ChevronRight />
            </Button>
          </div>
        ) : null}
      </DataStatus>
    </div>
  );
}
