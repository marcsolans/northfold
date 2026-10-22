"use client";

import { Badge, Button, Card, EmptyState, ErrorState, Skeleton, toast } from "@messer/ui";
import { useQueryClient } from "@tanstack/react-query";
import { Database, Upload } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { formatRelative, localeTag } from "@/lib/format";

import { errorMessage, kbKeys, useKbTables } from "./queries";
import { TableViewer } from "./table-viewer";
import type { KbTable, KnowledgeBase } from "./types";
import { uploadKnowledgeFile } from "./upload";

export function TablesTab({
  kb,
  canWrite,
  selectedTableId,
  onSelectTable,
}: {
  kb: KnowledgeBase;
  canWrite: boolean;
  selectedTableId: string | null;
  onSelectTable: (tableId: string | null) => void;
}) {
  const t = useTranslations("knowledge.tables");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const tables = useKbTables(kb.id);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = React.useState<number | null>(null);

  const selected = tables.data?.find((tbl) => tbl.id === selectedTableId) ?? null;

  const upload = async (file: File) => {
    setUploading(0);
    try {
      const created = await uploadKnowledgeFile<KbTable[]>(`/knowledge-bases/${kb.id}/tables`, file, setUploading);
      toast.success(t("imported", { count: created.length }));
      await qc.invalidateQueries({ queryKey: kbKeys.tables(kb.id) });
      void qc.invalidateQueries({ queryKey: kbKeys.files(kb.id) });
      void qc.invalidateQueries({ queryKey: kbKeys.schema(kb.id) });
      void qc.invalidateQueries({ queryKey: kbKeys.detail(kb.id), exact: true });
      const first = created[0];
      if (first) onSelectTable(first.id);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setUploading(null);
    }
  };

  if (selected) {
    return <TableViewer kbId={kb.id} table={selected} canWrite={canWrite} onBack={() => onSelectTable(null)} />;
  }

  const importButton = canWrite ? (
    <>
      <Button size="sm" variant="secondary" loading={uploading !== null} onClick={() => inputRef.current?.click()}>
        <Upload />
        {uploading !== null && uploading < 1 ? `${Math.round(uploading * 100)}%` : t("import")}
      </Button>
      <input
        ref={inputRef}
        type="file"
        accept=".csv,.tsv,.xlsx,.xlsm"
        className="sr-only"
        aria-label={t("import")}
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (file) void upload(file);
        }}
      />
    </>
  ) : null;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-fg-muted">{t("description")}</p>
        {importButton}
      </div>
      {tables.isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
      ) : tables.error ? (
        <ErrorState title={tc("errorTitle")} description={errorMessage(tables.error)} onRetry={() => void tables.refetch()} retryLabel={tc("retry")} />
      ) : (tables.data ?? []).length === 0 ? (
        <EmptyState icon={<Database />} title={t("empty")} description={t("emptyHint")} action={importButton} />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {(tables.data ?? []).map((table) => (
            <Card key={table.id} className="flex flex-col">
              <button
                type="button"
                onClick={() => onSelectTable(table.id)}
                className="flex flex-1 flex-col gap-2 p-4 text-left hover:bg-subtle/60"
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="truncate font-mono text-sm font-semibold">{table.name}</span>
                  <Badge tone="outline">{t(`source.${table.source === "sync" ? "sync" : table.source === "manual" ? "manual" : "upload"}`)}</Badge>
                </span>
                {table.description ? <span className="line-clamp-2 text-xs text-fg-muted">{table.description}</span> : null}
                <span className="tabular mt-auto flex items-center justify-between text-xs text-fg-subtle">
                  <span>
                    {t("rowsCount", { count: table.row_count })} ·{" "}
                    {t("columnsCount", { count: table.columns.length })}
                  </span>
                  <span>{formatRelative(table.updated_at, locale)}</span>
                </span>
              </button>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
