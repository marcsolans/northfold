"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  ConfirmDialog,
  Dialog,
  DialogContent,
  ErrorState,
  Field,
  Input,
  Select,
  SkeletonRows,
  Switch,
  Tooltip,
  TooltipProvider,
  cn,
  toast,
} from "@messer/ui";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowLeft, ArrowUp, Filter, Lock, Plus, Trash2, X } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { ApiError, http } from "@/lib/api";
import { formatNumber, localeTag } from "@/lib/format";

import { errorMessage, formatCell, kbKeys } from "./queries";
import {
  type FilterOp,
  type KbTable,
  LOGICAL_TYPES,
  type LogicalType,
  type RowFilter,
  type RowsResult,
} from "./types";

const PAGE_SIZE = 50;
const OPS: FilterOp[] = ["eq", "neq", "contains", "starts", "gt", "gte", "lt", "lte", "is_null", "not_null"];
const NO_VALUE_OPS = new Set<FilterOp>(["is_null", "not_null"]);

function TypeBadge({ type }: { type: string }) {
  const t = useTranslations("knowledge.types");
  return (
    <span className="rounded-sm border border-border px-1 py-px font-mono text-[10px] font-normal normal-case tracking-normal text-fg-subtle">
      {LOGICAL_TYPES.includes(type as LogicalType) ? t(type) : type}
    </span>
  );
}

function TypeEditor({
  kbId,
  table,
  column,
  onClose,
}: {
  kbId: string;
  table: KbTable;
  column: string | null;
  onClose: () => void;
}) {
  const t = useTranslations("knowledge.tables");
  const tt = useTranslations("knowledge.types");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const current = table.columns.find((c) => c.name === column);
  const [type, setType] = React.useState<LogicalType>(current?.type ?? "text");
  const [force, setForce] = React.useState(false);
  const [failure, setFailure] = React.useState<{ failures: number; examples: string[] } | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    setType(current?.type ?? "text");
    setForce(false);
    setFailure(null);
    setError(null);
  }, [column, current?.type]);

  const save = useMutation({
    mutationFn: () =>
      http.patch<KbTable>(`/knowledge-bases/${kbId}/tables/${table.id}/columns/${encodeURIComponent(column ?? "")}`, {
        type,
        force,
      }),
    onSuccess: () => {
      toast.success(t("typeChanged"));
      void qc.invalidateQueries({ queryKey: kbKeys.tables(kbId) });
      void qc.invalidateQueries({ queryKey: kbKeys.rows(kbId, table.id) });
      void qc.invalidateQueries({ queryKey: kbKeys.schema(kbId) });
      onClose();
    },
    onError: (err) => {
      if (err instanceof ApiError && err.code === "type_conversion_failed") {
        setFailure({
          failures: Number(err.details.failures ?? 0),
          examples: Array.isArray(err.details.examples) ? err.details.examples.map(String) : [],
        });
      } else {
        setError(errorMessage(err));
      }
    },
  });

  return (
    <Dialog open={column !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent title={t("typeTitle", { column: column ?? "" })} description={t("typeDescription")}>
        <div className="flex flex-col gap-3">
          {error ? <Alert tone="danger">{error}</Alert> : null}
          <Field label={t("type")}>
            <Select
              value={type}
              onValueChange={(v) => {
                setType(v as LogicalType);
                setFailure(null);
              }}
              options={LOGICAL_TYPES.map((value) => ({ value, label: tt(value), description: tt(`hint.${value}`) }))}
            />
          </Field>
          {failure ? (
            <Alert tone="warning" title={t("conversionFailed", { count: failure.failures })}>
              {failure.examples.length > 0 ? (
                <span className="font-mono text-xs">{failure.examples.join(" · ")}</span>
              ) : null}
            </Alert>
          ) : null}
          {failure ? (
            <label className="flex items-center gap-2 text-sm">
              <Switch checked={force} onCheckedChange={setForce} aria-label={t("force")} />
              {t("force")}
            </label>
          ) : null}
          <div className="mt-2 flex justify-end gap-2">
            <Button variant="secondary" onClick={onClose}>
              {tc("cancel")}
            </Button>
            <Button
              variant="primary"
              loading={save.isPending}
              disabled={type === current?.type || (failure !== null && !force)}
              onClick={() => {
                setError(null);
                save.mutate();
              }}
            >
              {t("applyType")}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function EditableCell({
  value,
  editable,
  onSave,
}: {
  value: unknown;
  editable: boolean;
  onSave: (value: string | null) => Promise<void>;
}) {
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const text = formatCell(value);
  if (!editing) {
    return (
      <span
        className={cn("block max-w-72 truncate", value === null && "text-fg-subtle", editable && "cursor-text")}
        title={text}
        onDoubleClick={() => {
          if (!editable) return;
          setDraft(text);
          setEditing(true);
        }}
      >
        {value === null ? "NULL" : text}
      </span>
    );
  }
  const commit = async () => {
    setSaving(true);
    try {
      await onSave(draft === "" ? null : draft);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };
  return (
    <Input
      autoFocus
      value={draft}
      disabled={saving}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => setEditing(false)}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          void commit();
        } else if (e.key === "Escape") {
          setEditing(false);
        }
      }}
      className="h-7 min-w-32"
    />
  );
}

export function TableViewer({
  kbId,
  table,
  canWrite,
  onBack,
}: {
  kbId: string;
  table: KbTable;
  canWrite: boolean;
  onBack: () => void;
}) {
  const t = useTranslations("knowledge.tables");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const [filters, setFilters] = React.useState<RowFilter[]>([]);
  const [draftFilters, setDraftFilters] = React.useState<RowFilter[]>([]);
  const [showFilters, setShowFilters] = React.useState(false);
  const [sort, setSort] = React.useState<{ column: string; order: "asc" | "desc" } | null>(null);
  const [offset, setOffset] = React.useState(0);
  const [typeColumn, setTypeColumn] = React.useState<string | null>(null);
  const [deleting, setDeleting] = React.useState(false);

  React.useEffect(() => {
    setFilters([]);
    setDraftFilters([]);
    setSort(null);
    setOffset(0);
  }, [table.id]);

  const rows = useQuery({
    queryKey: [...kbKeys.rows(kbId, table.id), filters, sort, offset],
    queryFn: () =>
      http.get<RowsResult>(`/knowledge-bases/${kbId}/tables/${table.id}/rows`, {
        filters: filters.length ? JSON.stringify(filters) : undefined,
        sort: sort?.column,
        order: sort?.order,
        limit: PAGE_SIZE,
        offset,
      }),
    placeholderData: keepPreviousData,
  });

  const remove = useMutation({
    mutationFn: () => http.del(`/knowledge-bases/${kbId}/tables/${table.id}`),
    onSuccess: () => {
      toast.success(t("deleted"));
      void qc.invalidateQueries({ queryKey: kbKeys.tables(kbId) });
      void qc.invalidateQueries({ queryKey: kbKeys.schema(kbId) });
      onBack();
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const pkColumns = table.primary_key.length ? table.primary_key : ["_row_id"];
  const data = rows.data;
  const columnIndex = new Map((data?.columns ?? []).map((c, i) => [c.name, i]));

  const saveCell = async (row: unknown[], column: string, value: string | null) => {
    const pk: Record<string, unknown> = {};
    for (const key of pkColumns) pk[key] = row[columnIndex.get(key) ?? -1];
    try {
      await http.patch(`/knowledge-bases/${kbId}/tables/${table.id}/rows`, { pk, column, value });
      toast.success(t("cellSaved"));
      await qc.invalidateQueries({ queryKey: kbKeys.rows(kbId, table.id) });
    } catch (err) {
      toast.error(errorMessage(err));
      throw err;
    }
  };

  const toggleSort = (column: string) => {
    setOffset(0);
    setSort((prev) =>
      prev?.column !== column ? { column, order: "asc" } : prev.order === "asc" ? { column, order: "desc" } : null,
    );
  };

  const columnOptions = [
    ...(table.primary_key.length ? [] : [{ value: "_row_id", label: "_row_id" }]),
    ...table.columns.map((c) => ({ value: c.name, label: c.name })),
  ];
  const total = data?.total ?? table.row_count;
  const lastLoad = table.last_load;

  return (
    <TooltipProvider>
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <button
              type="button"
              onClick={onBack}
              className="mb-1 flex items-center gap-1 text-xs text-fg-muted hover:text-fg [&_svg]:size-3.5"
            >
              <ArrowLeft aria-hidden />
              {t("allTables")}
            </button>
            <h3 className="flex items-center gap-2 font-mono text-md font-semibold">
              {table.name}
              <Badge tone="outline">{t(`source.${table.source === "sync" ? "sync" : table.source === "manual" ? "manual" : "upload"}`)}</Badge>
            </h3>
            {table.description ? <p className="mt-0.5 text-sm text-fg-muted">{table.description}</p> : null}
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" variant={showFilters ? "dark" : "secondary"} onClick={() => setShowFilters((v) => !v)}>
              <Filter />
              {filters.length ? t("filtersCount", { count: filters.length }) : t("filter")}
            </Button>
            {canWrite ? (
              <Button size="sm" variant="danger" onClick={() => setDeleting(true)}>
                <Trash2 />
                {tc("delete")}
              </Button>
            ) : null}
          </div>
        </div>

        {lastLoad && (lastLoad.invalid_values > 0 || lastLoad.skipped_rows > 0) ? (
          <Alert tone="warning" title={t("loadWarnings", { invalid: lastLoad.invalid_values, skipped: lastLoad.skipped_rows })}>
            {lastLoad.examples.length ? <span className="text-xs">{lastLoad.examples.join(" · ")}</span> : null}
          </Alert>
        ) : null}
        {data?.policy?.applied?.length ? <Alert tone="info">{t("policyApplied")}</Alert> : null}

        {showFilters ? (
          <Card className="flex flex-col gap-2 p-3">
            {draftFilters.length === 0 ? <p className="text-sm text-fg-subtle">{t("noFilters")}</p> : null}
            {draftFilters.map((f, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2">
                <Select
                  aria-label={t("column")}
                  className="w-44"
                  value={f.column}
                  onValueChange={(v) => setDraftFilters((prev) => prev.map((x, j) => (j === i ? { ...x, column: v } : x)))}
                  options={columnOptions}
                />
                <Select
                  aria-label={t("operator")}
                  className="w-40"
                  value={f.op}
                  onValueChange={(v) => setDraftFilters((prev) => prev.map((x, j) => (j === i ? { ...x, op: v as FilterOp } : x)))}
                  options={OPS.map((op) => ({ value: op, label: t(`ops.${op}`) }))}
                />
                {NO_VALUE_OPS.has(f.op) ? null : (
                  <Input
                    aria-label={t("value")}
                    className="w-48"
                    value={f.value ?? ""}
                    onChange={(e) => setDraftFilters((prev) => prev.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))}
                  />
                )}
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label={tc("remove")}
                  onClick={() => setDraftFilters((prev) => prev.filter((_, j) => j !== i))}
                >
                  <X />
                </Button>
              </div>
            ))}
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Button
                size="sm"
                variant="ghost"
                onClick={() =>
                  setDraftFilters((prev) => [...prev, { column: columnOptions[0]?.value ?? "", op: "eq", value: "" }])
                }
              >
                <Plus />
                {t("addFilter")}
              </Button>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => {
                    setDraftFilters([]);
                    setFilters([]);
                    setOffset(0);
                  }}
                >
                  {t("clearFilters")}
                </Button>
                <Button
                  size="sm"
                  variant="dark"
                  onClick={() => {
                    setFilters(draftFilters.filter((f) => f.column && (NO_VALUE_OPS.has(f.op) || (f.value ?? "") !== "")));
                    setOffset(0);
                  }}
                >
                  {t("applyFilters")}
                </Button>
              </div>
            </div>
          </Card>
        ) : null}

        <Card className="overflow-hidden">
          {rows.isLoading ? (
            <div className="p-4">
              <SkeletonRows rows={6} />
            </div>
          ) : rows.error ? (
            <div className="p-4">
              <ErrorState title={tc("errorTitle")} description={errorMessage(rows.error)} onRetry={() => void rows.refetch()} retryLabel={tc("retry")} />
            </div>
          ) : data ? (
            <div className="max-h-[60vh] overflow-auto">
              <table className="w-full border-collapse text-sm">
                <thead className="sticky top-0 z-10 bg-subtle">
                  <tr className="border-b border-border">
                    {data.columns.map((col) => {
                      const sorted = sort?.column === col.name ? sort.order : null;
                      const isLogical = table.columns.some((c) => c.name === col.name);
                      return (
                        <th key={col.name} className="whitespace-nowrap px-3 py-1.5 text-left align-middle text-xs font-medium text-fg-subtle">
                          <span className="flex items-center gap-1.5">
                            <button
                              type="button"
                              className="flex items-center gap-1 font-mono text-fg hover:underline"
                              onClick={() => toggleSort(col.name)}
                              aria-label={t("sortBy", { column: col.name })}
                            >
                              {col.name}
                              {sorted === "asc" ? <ArrowUp className="size-3" /> : sorted === "desc" ? <ArrowDown className="size-3" /> : null}
                            </button>
                            {canWrite && isLogical && !col.pk ? (
                              <button type="button" onClick={() => setTypeColumn(col.name)} aria-label={t("changeType", { column: col.name })}>
                                <TypeBadge type={col.type} />
                              </button>
                            ) : (
                              <TypeBadge type={col.type} />
                            )}
                            {col.pk ? <Badge tone="info">PK</Badge> : null}
                            {col.masked ? (
                              <Tooltip content={t("masked")}>
                                <span className="inline-flex" role="img" aria-label={t("masked")}>
                                  <Lock className="size-3 text-warning" aria-hidden />
                                </span>
                              </Tooltip>
                            ) : null}
                          </span>
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {data.rows.length === 0 ? (
                    <tr>
                      <td colSpan={Math.max(1, data.columns.length)} className="px-3 py-8 text-center text-fg-subtle">
                        {filters.length ? t("noMatches") : t("emptyTable")}
                      </td>
                    </tr>
                  ) : (
                    data.rows.map((row, i) => (
                      <tr key={i} className="hover:bg-subtle/60">
                        {data.columns.map((col, j) => (
                          <td key={col.name} className="px-3 py-1.5 align-middle font-mono text-xs">
                            <EditableCell
                              value={row[j] ?? null}
                              editable={canWrite && !col.pk && !col.masked && col.name !== "_row_id"}
                              onSave={(value) => saveCell(row, col.name, value)}
                            />
                          </td>
                        ))}
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          ) : null}
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border bg-subtle px-3 py-2 text-xs text-fg-muted">
            <span className="tabular">
              {total === 0
                ? t("rowsNone")
                : t("rowsRange", {
                    from: formatNumber(offset + 1, locale),
                    to: formatNumber(Math.min(offset + PAGE_SIZE, total), locale),
                    total: formatNumber(total, locale),
                  })}
              {canWrite ? ` · ${t("editHint")}` : ""}
            </span>
            <span className="flex gap-1">
              <Button size="sm" variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
                {t("previous")}
              </Button>
              <Button
                size="sm"
                variant="secondary"
                disabled={offset + PAGE_SIZE >= total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                {t("next")}
              </Button>
            </span>
          </div>
        </Card>

        <TypeEditor kbId={kbId} table={table} column={typeColumn} onClose={() => setTypeColumn(null)} />
        <ConfirmDialog
          open={deleting}
          onOpenChange={setDeleting}
          title={t("deleteConfirm", { name: table.name })}
          description={t("deleteDescription")}
          confirmLabel={tc("delete")}
          cancelLabel={tc("cancel")}
          loading={remove.isPending}
          onConfirm={() => remove.mutate()}
        />
      </div>
    </TooltipProvider>
  );
}
