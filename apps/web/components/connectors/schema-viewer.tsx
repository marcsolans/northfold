"use client";

import { Badge, EmptyState, ErrorState, Input, SkeletonRows, TBody, TD, TH, THead, TR, Table } from "@messer/ui";
import { Database, KeyRound, Search } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { formatNumber, localeTag } from "@/lib/format";

import { errorMessage, useSchema } from "./queries";

export function SchemaViewer({ connectionId }: { connectionId: string }) {
  const t = useTranslations("connectors.schema");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const schema = useSchema(connectionId, true);
  const [query, setQuery] = React.useState("");
  const [open, setOpen] = React.useState<string | null>(null);

  if (schema.isLoading) return <SkeletonRows rows={6} />;
  if (schema.error) {
    return <ErrorState title={tc("errorTitle")} description={errorMessage(schema.error)} onRetry={() => void schema.refetch()} retryLabel={tc("retry")} />;
  }
  const q = query.trim().toLowerCase();
  const tables = (schema.data?.tables ?? []).filter(
    (tbl) =>
      !q ||
      `${tbl.schema}.${tbl.name}`.toLowerCase().includes(q) ||
      tbl.columns.some((c) => c.name.toLowerCase().includes(q)),
  );
  if ((schema.data?.tables ?? []).length === 0) return <EmptyState icon={<Database />} title={t("empty")} />;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <div className="relative w-full max-w-sm">
          <Search className="pointer-events-none absolute left-2.5 top-2 size-4 text-fg-subtle" aria-hidden />
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("search")} aria-label={t("search")} className="pl-8" />
        </div>
        <span className="tabular text-xs text-fg-subtle">{t("tables", { count: tables.length })}</span>
      </div>
      <div className="flex flex-col gap-2">
        {tables.map((tbl) => {
          const id = `${tbl.schema}.${tbl.name}`;
          const expanded = open === id || (q !== "" && tables.length <= 3);
          return (
            <div key={id} className="rounded-md border border-border bg-surface">
              <button
                type="button"
                aria-expanded={expanded}
                onClick={() => setOpen(expanded ? null : id)}
                className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left"
              >
                <span className="min-w-0">
                  <span className="font-mono text-sm font-medium">{id}</span>
                  {tbl.kind !== "table" ? <Badge className="ml-2">{t("view")}</Badge> : null}
                  {tbl.comment ? <span className="block truncate text-xs text-fg-muted">{tbl.comment}</span> : null}
                </span>
                <span className="tabular shrink-0 text-xs text-fg-subtle">
                  {t("rows", { count: formatNumber(tbl.row_estimate, locale) })} · {tbl.columns.length}
                </span>
              </button>
              {expanded ? (
                <div className="border-t border-border">
                  <Table>
                    <THead>
                      <tr>
                        <TH>{t("column")}</TH>
                        <TH>{t("type")}</TH>
                        <TH className="hidden sm:table-cell">{t("kbType")}</TH>
                        <TH className="hidden sm:table-cell">{t("nullable")}</TH>
                        <TH className="hidden md:table-cell">{t("comment")}</TH>
                      </tr>
                    </THead>
                    <TBody>
                      {tbl.columns.map((c) => (
                        <TR key={c.name}>
                          <TD className="font-mono text-xs">
                            <span className="flex items-center gap-1">
                              {c.pk ? <KeyRound className="size-3 text-accent" aria-label={t("pk")} /> : null}
                              {c.name}
                            </span>
                          </TD>
                          <TD className="font-mono text-xs text-fg-muted">{c.type}</TD>
                          <TD className="hidden sm:table-cell">
                            <Badge tone="outline">{c.kb_type}</Badge>
                          </TD>
                          <TD className="hidden text-fg-muted sm:table-cell">{c.nullable ? tc("yes") : tc("no")}</TD>
                          <TD className="hidden max-w-xs truncate text-xs text-fg-muted md:table-cell">{c.comment ?? ""}</TD>
                        </TR>
                      ))}
                    </TBody>
                  </Table>
                  {tbl.foreign_keys.length > 0 ? (
                    <div className="flex flex-wrap items-center gap-2 border-t border-border px-3 py-2 text-xs text-fg-muted">
                      <span className="font-medium uppercase tracking-wide text-fg-subtle">{t("fk")}</span>
                      {tbl.foreign_keys.map((fk) => (
                        <span key={fk.name} className="font-mono">
                          {fk.columns.join(", ")}{" "}
                          {t("references", { table: `${fk.ref_schema}.${fk.ref_table}`, columns: fk.ref_columns.join(", ") })}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
