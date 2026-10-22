"use client";

import {
  ActionButton,
  ApprovalsInbox,
  ConfirmDialog,
  type ApprovalItem,
  CalendarView,
  DataChart,
  DataForm,
  type DataFormField,
  DataPanel,
  DataTable,
  type DataTableColumn,
  FileDropzone,
  FilterBar,
  type FilterValues,
  KpiCard,
  RecordList,
  toast,
} from "@messer/ui";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { LogIn } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { ApiError } from "@/lib/api";

import type { DataLabels } from "../labels";
import type { InterfaceSource } from "../source";
import type {
  ActionResult,
  ColumnDef,
  ComponentDef,
  FilterDef,
  FormFieldDef,
  RowAction,
  Scalar,
} from "../types";
import { messageOf } from "../util";
import { ChatView } from "./chat-view";

function str(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}

function num(value: unknown): number | undefined {
  return typeof value === "number" ? value : undefined;
}

function arr<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function initialFilters(filters: FilterDef[]): FilterValues {
  const out: FilterValues = {};
  for (const f of filters) if (f.default !== null && f.default !== undefined) out[f.name] = String(f.default);
  return out;
}

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = React.useState(value);
  React.useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), ms);
    return () => window.clearTimeout(id);
  }, [value, ms]);
  return debounced;
}

function inputNames(binding: ComponentDef["binding"]): string[] {
  if (!binding) return [];
  if ("inputs" in binding && Array.isArray(binding.inputs)) return binding.inputs;
  if ("params" in binding) {
    return binding.params.flatMap((p) => (p !== null && typeof p === "object" && "input" in p ? [p.input] : []));
  }
  return [];
}

/** Inputs of a data component: filters (bound parameters) and an optional server-side search box. */
function useInputs(comp: ComponentDef) {
  const filters = arr<FilterDef>(comp.props.filters);
  const binding = comp.binding;
  let serverSearch: string | null = null;
  if (binding?.kind === "knowledge_search") {
    serverSearch = "query_input" in binding ? (binding.query_input ?? null) : "search";
  } else if (inputNames(binding).includes("search")) {
    serverSearch = "search";
  }
  const [values, setValues] = React.useState<FilterValues>(() => initialFilters(filters));
  const [search, setSearch] = React.useState("");
  const inputs = React.useMemo(() => {
    const out: Record<string, Scalar> = { ...values };
    if (serverSearch && search.trim()) out[serverSearch] = search.trim();
    return out;
  }, [values, search, serverSearch]);
  return { filters, values, setValues, search, setSearch, serverSearch, inputs: useDebounced(inputs, 350) };
}

function useData(source: InterfaceSource, comp: ComponentDef, inputs: Record<string, Scalar>, draft: ComponentDef | null) {
  return useQuery({
    queryKey: [source.key, "data", comp.id, inputs, draft ? JSON.stringify(draft) : null],
    queryFn: () => source.data(comp.id, inputs, draft),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}

function outcomeMessage(result: ActionResult, t: ReturnType<typeof useTranslations>, success?: string): { ok: boolean; message: string } {
  if (result.status === "paused") return { ok: true, message: t("data.approvalPending") };
  if (result.status !== "success") return { ok: false, message: result.error || t("data.actionFailed") };
  return { ok: true, message: success || result.text || t("data.actionDone") };
}

function LoginRequired() {
  const t = useTranslations("interfaces");
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center text-sm text-fg-muted">
      <LogIn className="size-5 text-fg-subtle" aria-hidden />
      {t("data.loginToUse")}
    </div>
  );
}

function useRowAction(source: InterfaceSource, comp: ComponentDef, draft: ComponentDef | null, labels: DataLabels) {
  const t = useTranslations("interfaces");
  const action = comp.props.row_action as RowAction | null | undefined;
  const [busyRow, setBusyRow] = React.useState<number | null>(null);
  const [asking, setAsking] = React.useState<{ row: Record<string, unknown>; index: number } | null>(null);
  const run = async (row: Record<string, unknown>, index: number) => {
    setBusyRow(index);
    try {
      const outcome = outcomeMessage(await source.action(comp.id, { row, row_action: true }, draft), t);
      if (outcome.ok) toast.success(outcome.message);
      else toast.error(outcome.message);
    } catch (err) {
      toast.error(messageOf(err, t("data.actionFailed")));
    } finally {
      setBusyRow(null);
      setAsking(null);
    }
  };
  if (!action) return { rowAction: null, dialog: null };
  return {
    rowAction: {
      label: action.label,
      busyRow,
      onRun: (row: Record<string, unknown>, index: number) => {
        if (action.confirm) setAsking({ row, index });
        else void run(row, index);
      },
    },
    dialog: action.confirm ? (
      <ConfirmDialog
        open={asking !== null}
        onOpenChange={(open) => (open ? undefined : setAsking(null))}
        title={labels.action.confirmTitle}
        description={action.confirm}
        confirmLabel={action.label}
        cancelLabel={labels.action.cancel}
        destructive={false}
        loading={busyRow !== null}
        onConfirm={() => (asking ? run(asking.row, asking.index) : undefined)}
      />
    ) : null,
  };
}

/** One component of an interface, rendered with its live data or behaviour. */
export function ComponentView({
  comp,
  source,
  labels,
  draft = null,
  bare = false,
}: {
  comp: ComponentDef;
  source: InterfaceSource;
  labels: DataLabels;
  /** Unsaved definition to preview (Studio editor). */
  draft?: ComponentDef | null;
  /** No panel chrome (full-page chat). */
  bare?: boolean;
}) {
  const t = useTranslations("interfaces");
  const body = <ComponentBody comp={comp} source={source} labels={labels} draft={draft} />;
  if (bare) return body;
  return (
    <DataPanel
      title={comp.type === "kpi" ? undefined : comp.title || undefined}
      description={comp.type === "kpi" ? undefined : comp.description || undefined}
      bodyClassName={comp.type === "chat" ? "p-2" : undefined}
      className="h-full"
    >
      <React.Suspense fallback={<p className="text-sm text-fg-muted">{t("data.loading")}</p>}>{body}</React.Suspense>
    </DataPanel>
  );
}

function ComponentBody({
  comp,
  source,
  labels,
  draft,
}: {
  comp: ComponentDef;
  source: InterfaceSource;
  labels: DataLabels;
  draft: ComponentDef | null;
}) {
  switch (comp.type) {
    case "data_table":
    case "record_list":
    case "chart":
    case "calendar":
      return <TabularView comp={comp} source={source} labels={labels} draft={draft} />;
    case "kpi":
      return <KpiView comp={comp} source={source} labels={labels} draft={draft} />;
    case "form":
      return <FormView comp={comp} source={source} labels={labels} draft={draft} />;
    case "action_button":
      return <ButtonView comp={comp} source={source} labels={labels} draft={draft} />;
    case "file_upload":
      return source.member ? <UploadView comp={comp} source={source} labels={labels} /> : <LoginRequired />;
    case "approvals_inbox":
      return source.member ? <ApprovalsView comp={comp} source={source} labels={labels} draft={draft} /> : <LoginRequired />;
    case "chat":
      return <ChatView comp={comp} source={source} labels={labels} />;
    default:
      return null;
  }
}

function TabularView({ comp, source, labels, draft }: { comp: ComponentDef; source: InterfaceSource; labels: DataLabels; draft: ComponentDef | null }) {
  const t = useTranslations("interfaces");
  const { filters, values, setValues, search, setSearch, serverSearch, inputs } = useInputs(comp);
  const query = useData(source, comp, inputs, draft);
  const { rowAction, dialog } = useRowAction(source, comp, draft, labels);
  const rows = query.data?.rows ?? [];
  const error = query.error ? messageOf(query.error, t("data.loadFailed")) : null;
  const loading = query.isPending;
  const p = comp.props;
  const bar =
    filters.length > 0 || serverSearch ? (
      <FilterBar
        filters={filters.map((f) => ({ ...f, required: f.default !== null && f.default !== undefined }))}
        values={values}
        onChange={setValues}
        search={search}
        onSearchChange={serverSearch && (comp.type !== "chart" || filters.length > 0) ? setSearch : undefined}
        labels={labels.filters}
        className="mb-2"
      />
    ) : null;

  if (comp.type === "chart") {
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        {bar}
        <DataChart
          rows={rows}
          kind={(str(p.chart) as "bar" | "line" | "pie" | "area" | undefined) ?? "bar"}
          x={str(p.x) ?? null}
          y={arr<string>(p.y)}
          stacked={p.stacked === true}
          format={(str(p.format) as "number" | "currency" | "percent" | undefined) ?? "number"}
          currency={str(p.currency) ?? "EUR"}
          legend={p.legend !== false}
          loading={loading}
          error={error}
          onRetry={() => void query.refetch()}
          labels={labels.chart}
          locale={labels.locale}
          title={comp.title ?? undefined}
        />
      </div>
    );
  }
  if (comp.type === "calendar") {
    return (
      <CalendarView
        rows={rows}
        dateField={str(p.date_field) ?? ""}
        endField={str(p.end_field) ?? null}
        titleField={str(p.title_field) ?? null}
        view={p.view === "agenda" ? "agenda" : "month"}
        loading={loading}
        error={error}
        onRetry={() => void query.refetch()}
        labels={labels.calendar}
        locale={labels.locale}
      />
    );
  }
  if (comp.type === "record_list") {
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        {bar}
        <RecordList
          rows={rows}
          titleField={str(p.title_field) ?? null}
          subtitleField={str(p.subtitle_field) ?? null}
          metaFields={arr<string>(p.meta_fields)}
          badgeField={str(p.badge_field) ?? null}
          pageSize={num(p.page_size) ?? 10}
          searchable={p.searchable === true && !serverSearch}
          loading={loading}
          error={error}
          emptyText={str(p.empty_text) ?? null}
          onRetry={() => void query.refetch()}
          rowAction={rowAction}
          labels={labels.list}
          locale={labels.locale}
        />
        {dialog}
      </div>
    );
  }
  const columns: DataTableColumn[] = arr<ColumnDef>(p.columns).map((c) => ({
    key: c.key,
    label: c.label,
    format: c.format,
    align: c.align,
  }));
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {bar}
      <DataTable
        rows={rows}
        columns={columns}
        pageSize={num(p.page_size) ?? 10}
        searchable={p.searchable === true && !serverSearch}
        loading={loading}
        error={error}
        truncated={query.data?.truncated}
        emptyText={str(p.empty_text) ?? null}
        onRetry={() => void query.refetch()}
        rowAction={rowAction}
        labels={labels.table}
        locale={labels.locale}
        caption={comp.title ?? undefined}
      />
      {dialog}
    </div>
  );
}

function KpiView({ comp, source, labels, draft }: { comp: ComponentDef; source: InterfaceSource; labels: DataLabels; draft: ComponentDef | null }) {
  const t = useTranslations("interfaces");
  const query = useData(source, comp, {}, draft);
  const p = comp.props;
  const row = query.data?.rows[0] ?? {};
  const valueKey = str(p.value) ?? query.data?.columns[0] ?? "";
  const deltaKey = str(p.delta);
  return (
    <KpiCard
      label={comp.title || undefined}
      value={row[valueKey]}
      format={(str(p.format) as "number" | "currency" | "percent" | "text" | undefined) ?? "number"}
      currency={str(p.currency) ?? "EUR"}
      decimals={num(p.decimals) ?? null}
      delta={deltaKey ? row[deltaKey] : undefined}
      deltaFormat={p.delta_format === "number" ? "number" : "percent"}
      trend={p.trend === "down_is_good" ? "down_is_good" : "up_is_good"}
      hint={str(p.hint) ?? comp.description ?? undefined}
      loading={query.isPending}
      error={query.error ? messageOf(query.error, t("data.loadFailed")) : null}
      onRetry={() => void query.refetch()}
      labels={labels.kpi}
      locale={labels.locale}
    />
  );
}

function FormView({ comp, source, labels, draft }: { comp: ComponentDef; source: InterfaceSource; labels: DataLabels; draft: ComponentDef | null }) {
  const t = useTranslations("interfaces");
  const p = comp.props;
  const fields = React.useMemo<DataFormField[]>(() => arr<FormFieldDef>(p.fields), [p.fields]);
  return (
    <DataForm
      fields={fields}
      submitLabel={str(p.submit_label) ?? null}
      successMessage={str(p.success_message) ?? null}
      resetOnSubmit={p.reset_on_submit !== false}
      labels={labels.form}
      onSubmit={async (values) => {
        try {
          const result = await source.action(comp.id, { values }, draft);
          return outcomeMessage(result, t, str(p.success_message));
        } catch (err) {
          const field = err instanceof ApiError && typeof err.details.field === "string" ? err.details.field : null;
          return { ok: false, message: messageOf(err, t("data.actionFailed")), field };
        }
      }}
    />
  );
}

function ButtonView({ comp, source, labels, draft }: { comp: ComponentDef; source: InterfaceSource; labels: DataLabels; draft: ComponentDef | null }) {
  const t = useTranslations("interfaces");
  const p = comp.props;
  const variant = p.variant === "secondary" || p.variant === "danger" ? p.variant : "primary";
  return (
    <ActionButton
      label={str(p.label) ?? comp.title ?? t("data.run")}
      variant={variant}
      description={str(p.description) ?? null}
      confirm={str(p.confirm) ?? null}
      labels={labels.action}
      onRun={async () => {
        try {
          return outcomeMessage(await source.action(comp.id, {}, draft), t, str(p.success_message));
        } catch (err) {
          return { ok: false, message: messageOf(err, t("data.actionFailed")) };
        }
      }}
    />
  );
}

function UploadView({ comp, source, labels }: { comp: ComponentDef; source: InterfaceSource; labels: DataLabels }) {
  const t = useTranslations("interfaces");
  const p = comp.props;
  return (
    <FileDropzone
      accept={arr<string>(p.accept)}
      maxMb={num(p.max_mb) ?? 20}
      multiple={p.multiple !== false}
      label={str(p.label) ?? null}
      help={str(p.help) ?? null}
      labels={labels.upload}
      onUpload={async (file) => {
        try {
          const res = await source.upload(comp.id, file);
          if (res.run && res.run.status !== "success" && res.run.status !== "paused") {
            return { ok: false, message: res.run.error || t("data.actionFailed") };
          }
          return { ok: true, message: t("data.uploadedQueued") };
        } catch (err) {
          return { ok: false, message: messageOf(err, labels.upload.failed) };
        }
      }}
    />
  );
}

function ApprovalsView({ comp, source, labels, draft }: { comp: ComponentDef; source: InterfaceSource; labels: DataLabels; draft: ComponentDef | null }) {
  const t = useTranslations("interfaces");
  const queryClient = useQueryClient();
  const query = useData(source, comp, {}, draft);
  const items = (query.data?.rows ?? []) as unknown as ApprovalItem[];
  return (
    <ApprovalsInbox
      items={items}
      pageSize={num(comp.props.page_size) ?? 10}
      loading={query.isPending}
      error={query.error ? messageOf(query.error, t("data.loadFailed")) : null}
      onRetry={() => void query.refetch()}
      labels={labels.approvals}
      locale={labels.locale}
      onDecide={async (id, decision, comment) => {
        try {
          await source.decide(comp.id, id, decision, comment);
          toast.success(decision === "approve" ? t("data.approved") : t("data.denied"));
        } catch (err) {
          toast.error(messageOf(err, t("data.actionFailed")));
        } finally {
          await queryClient.invalidateQueries({ queryKey: [source.key, "data", comp.id] });
        }
      }}
    />
  );
}
