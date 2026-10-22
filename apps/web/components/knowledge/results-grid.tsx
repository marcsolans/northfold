"use client";

import { Button, CopyButton, cn } from "@messer/ui";
import { Download } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { formatNumber, localeTag } from "@/lib/format";

import { formatCell } from "./queries";

const PAGE = 200;

function toCsv(columns: string[], rows: unknown[][]): string {
  const escape = (value: unknown) => {
    const text = formatCell(value);
    return /[",\n;]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  return [columns.map(escape).join(","), ...rows.map((r) => r.map(escape).join(","))].join("\n");
}

/** Read-only grid for query results, paginated client-side, with CSV copy/download. */
export function ResultsGrid({
  columns,
  columnTypes,
  rows,
  className,
}: {
  columns: string[];
  columnTypes?: string[];
  rows: unknown[][];
  className?: string;
}) {
  const t = useTranslations("knowledge.results");
  const locale = localeTag(useLocale());
  const [page, setPage] = React.useState(0);
  React.useEffect(() => setPage(0), [rows]);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  const visible = rows.slice(page * PAGE, page * PAGE + PAGE);
  const csv = React.useMemo(() => toCsv(columns, rows), [columns, rows]);

  const download = () => {
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "resultado.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className={cn("flex flex-col overflow-hidden rounded-md border border-border", className)}>
      <div className="max-h-[50vh] overflow-auto">
        <table className="w-full border-collapse text-xs">
          <thead className="sticky top-0 bg-subtle">
            <tr className="border-b border-border">
              <th className="w-10 px-2 py-1.5 text-right font-medium text-fg-subtle">#</th>
              {columns.map((c, i) => (
                <th key={`${c}-${i}`} className="whitespace-nowrap px-3 py-1.5 text-left font-medium">
                  <span className="font-mono text-fg">{c}</span>
                  {columnTypes?.[i] ? <span className="ml-1.5 font-mono text-[10px] text-fg-subtle">{columnTypes[i]}</span> : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {visible.map((row, i) => (
              <tr key={i} className="hover:bg-subtle/60">
                <td className="tabular px-2 py-1 text-right text-fg-subtle">{page * PAGE + i + 1}</td>
                {row.map((value, j) => (
                  <td key={j} className={cn("max-w-96 truncate px-3 py-1 font-mono", value === null && "text-fg-subtle")} title={formatCell(value)}>
                    {value === null ? "NULL" : formatCell(value)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between gap-2 border-t border-border bg-subtle px-3 py-1.5 text-xs text-fg-muted">
        <span className="tabular">{t("rows", { count: rows.length, formatted: formatNumber(rows.length, locale) })}</span>
        <span className="flex items-center gap-1">
          {pages > 1 ? (
            <>
              <Button size="sm" variant="ghost" disabled={page === 0} onClick={() => setPage(page - 1)}>
                {t("previous")}
              </Button>
              <span className="tabular">
                {page + 1}/{pages}
              </span>
              <Button size="sm" variant="ghost" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>
                {t("next")}
              </Button>
            </>
          ) : null}
          <CopyButton value={csv} label={t("copyCsv")} />
          <Button size="icon-sm" variant="ghost" onClick={download} aria-label={t("downloadCsv")}>
            <Download />
          </Button>
        </span>
      </div>
    </div>
  );
}
