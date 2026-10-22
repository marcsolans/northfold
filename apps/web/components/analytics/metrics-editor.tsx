"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  ConfirmDialog,
  Dialog,
  DialogContent,
  EmptyState,
  ErrorState,
  Field,
  Input,
  RadioCards,
  Select,
  Sheet,
  SkeletonRows,
  Spinner,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  Textarea,
  toast,
} from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Gauge, LineChart, Plus } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { ApiError, http } from "@/lib/api";
import { localeTag } from "@/lib/format";
import { useRole } from "@/lib/hooks/use-me";

import { MetricValuesChart } from "./charts";
import { browserTimeZone } from "./filters";
import { formatMetric } from "./format";
import { analyticsKeys, useCustomMetrics } from "./queries";
import type {
  CustomMetric,
  MetricAggregate,
  MetricDefinition,
  MetricField,
  MetricSource,
  MetricValues,
  SpanKind,
} from "./types";

const AGGREGATES: MetricAggregate[] = ["count", "sum", "avg", "min", "max", "p50", "p95"];
const SPAN_FIELDS: MetricField[] = ["cost_usd", "duration", "tokens", "input_tokens", "output_tokens"];
const RUN_FIELDS: MetricField[] = ["cost_usd", "credits", "duration", "tokens", "input_tokens", "output_tokens"];
const KINDS: SpanKind[] = ["llm", "tool", "step", "agent", "workflow", "guardrail", "guard"];
const ANY = "__any__";
const DAY_MS = 86400_000;

function windowQuery(days: number) {
  const until = Math.ceil(Date.now() / 60_000) * 60_000;
  return { since: new Date(until - days * DAY_MS).toISOString(), until: new Date(until).toISOString(), tz: browserTimeZone() };
}

function apiErrorText(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    const errors = err.details.errors;
    if (Array.isArray(errors) && errors.length > 0) {
      const first = errors[0] as { msg?: string; loc?: string[] };
      if (first.msg) return first.msg.replace(/^Value error, /, "");
    }
    return err.message || fallback;
  }
  return fallback;
}

interface FormState {
  name: string;
  description: string;
  source: MetricSource;
  aggregate: MetricAggregate;
  field: MetricField;
  kind: string;
  nameGlob: string;
  status: string;
  model: string;
  pathGlob: string;
  outputContains: string;
  error: string;
}

function initialForm(m: CustomMetric | null): FormState {
  const d = m?.definition;
  const f = d?.filter ?? {};
  return {
    name: m?.name ?? "",
    description: m?.description ?? "",
    source: d?.source ?? "spans",
    aggregate: d?.aggregate ?? "count",
    field: d?.field ?? "cost_usd",
    kind: f.kind ?? ANY,
    nameGlob: f.name ?? "",
    status: f.status ?? "",
    model: f.model ?? "",
    pathGlob: f.path_glob ?? "",
    outputContains: f.output_contains ?? "",
    error: f.error === true ? "yes" : f.error === false ? "no" : ANY,
  };
}

function toDefinition(form: FormState): MetricDefinition {
  const spans = form.source === "spans";
  const text = (v: string) => (v.trim() ? v.trim() : null);
  return {
    source: form.source,
    aggregate: form.aggregate,
    field: form.aggregate === "count" ? null : form.field,
    filter: {
      kind: spans && form.kind !== ANY ? (form.kind as SpanKind) : null,
      name: text(form.nameGlob),
      status: text(form.status),
      model: text(form.model),
      path_glob: spans ? text(form.pathGlob) : null,
      output_contains: text(form.outputContains),
      error: form.error === ANY ? null : form.error === "yes",
    },
  };
}

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = React.useState(value);
  React.useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), ms);
    return () => window.clearTimeout(id);
  }, [value, ms]);
  return debounced;
}

export function DefinitionSummary({ definition }: { definition: MetricDefinition }) {
  const t = useTranslations("analytics.metrics");
  const f = definition.filter ?? {};
  const chips: string[] = [];
  if (f.kind) chips.push(`${t("fields.kind")}: ${t(`kinds.${f.kind}`)}`);
  if (f.name) chips.push(`${definition.source === "runs" ? t("fields.agent") : t("fields.name")}: ${f.name}`);
  if (f.status) chips.push(`${t("fields.status")}: ${f.status}`);
  if (f.model) chips.push(`${t("fields.model")}: ${f.model}`);
  if (f.path_glob) chips.push(`${t("fields.path")}: ${f.path_glob}`);
  if (f.output_contains) chips.push(`${t("fields.output")}: “${f.output_contains}”`);
  if (f.error !== null && f.error !== undefined) chips.push(f.error ? t("withErrors") : t("withoutErrors"));
  return (
    <span className="flex flex-col gap-1">
      <span className="text-sm">
        {t(`aggregates.${definition.aggregate}`)}
        {definition.field ? ` · ${t(`fieldNames.${definition.field}`)}` : ""} · {t(`sources.${definition.source}`)}
      </span>
      {chips.length ? (
        <span className="flex flex-wrap gap-1">
          {chips.map((c) => (
            <Badge key={c} tone="outline" className="max-w-full truncate font-mono text-[11px]">
              {c}
            </Badge>
          ))}
        </span>
      ) : null}
    </span>
  );
}

function PreviewPanel({ definition, enabled }: { definition: MetricDefinition; enabled: boolean }) {
  const t = useTranslations("analytics.metrics");
  const locale = localeTag(useLocale());
  const debounced = useDebounced(definition, 400);
  const key = JSON.stringify(debounced);
  // The preview endpoint is a POST without side effects: cache it like a query keyed by the definition.
  const result = useQuery({
    queryKey: ["metrics", "preview-post", key],
    queryFn: async () => {
      const q = windowQuery(7);
      const qs = new URLSearchParams(q).toString();
      return http.post<MetricValues>(`/metrics/preview?${qs}`, { definition: debounced } as unknown as Record<string, unknown>);
    },
    enabled,
    retry: false,
    placeholderData: (prev) => prev,
  });
  const data = result.data;
  return (
    <div className="rounded-md border border-border bg-subtle p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="text-xs font-medium text-fg-subtle">{t("previewTitle")}</p>
        {result.isFetching ? <Spinner className="size-3" /> : null}
      </div>
      {!enabled ? (
        <p className="text-sm text-fg-muted">{t("previewIncomplete")}</p>
      ) : result.error ? (
        <Alert tone="danger">{apiErrorText(result.error, t("previewError"))}</Alert>
      ) : data ? (
        <>
          <p className="text-lg font-semibold text-fg">{formatMetric(data.total, data.unit, locale)}</p>
          <MetricValuesChart
            points={data.points}
            bucket={data.bucket}
            name={t("previewSeries")}
            additive={definition.aggregate === "count" || definition.aggregate === "sum"}
            format={(v) => formatMetric(v, data.unit, locale)}
          />
        </>
      ) : (
        <SkeletonRows rows={2} />
      )}
    </div>
  );
}

function MetricDialog({ open, onOpenChange, editing }: { open: boolean; onOpenChange: (o: boolean) => void; editing: CustomMetric | null }) {
  const t = useTranslations("analytics.metrics");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const [form, setForm] = React.useState<FormState>(() => initialForm(editing));
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (open) {
      setForm(initialForm(editing));
      setError(null);
    }
  }, [open, editing]);
  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => setForm((f) => ({ ...f, [key]: value }));
  const definition = toDefinition(form);
  const fields = form.source === "spans" ? SPAN_FIELDS : RUN_FIELDS;
  const fieldValue: MetricField = fields.includes(form.field) ? form.field : (fields[0] ?? "cost_usd");
  const valid = form.name.trim().length > 0;

  const save = useMutation({
    mutationFn: () => {
      const body = { name: form.name.trim(), description: form.description.trim(), definition: { ...definition, field: form.aggregate === "count" ? null : fieldValue } };
      return editing
        ? http.patch<CustomMetric>(`/metrics/${editing.id}`, body as unknown as Record<string, unknown>)
        : http.post<CustomMetric>("/metrics", body as unknown as Record<string, unknown>);
    },
    onSuccess: () => {
      toast.success(editing ? t("updated") : t("created"));
      onOpenChange(false);
      void qc.invalidateQueries({ queryKey: analyticsKeys.metrics });
      void qc.invalidateQueries({ queryKey: analyticsKeys.alarmCatalog });
    },
    onError: (err) => setError(apiErrorText(err, tc("errorGeneric"))),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent wide title={editing ? t("editTitle") : t("newTitle")} description={t("formDescription")}>
        <form
          className="grid gap-4 lg:grid-cols-[1fr_20rem]"
          onSubmit={(e) => {
            e.preventDefault();
            if (valid) save.mutate();
          }}
        >
          <div className="flex min-w-0 flex-col gap-3">
            {error ? <Alert tone="danger">{error}</Alert> : null}
            <Field label={tc("name")} htmlFor="metric-name">
              <Input id="metric-name" required autoFocus maxLength={120} value={form.name} onChange={(e) => set("name", e.target.value)} />
            </Field>
            <Field label={tc("description")} htmlFor="metric-description" hint={tc("optional")}>
              <Textarea id="metric-description" rows={2} maxLength={2000} value={form.description} onChange={(e) => set("description", e.target.value)} />
            </Field>
            <Field label={t("fields.source")}>
              <RadioCards
                value={form.source}
                onValueChange={(v) => set("source", v as MetricSource)}
                options={(["spans", "runs"] as const).map((s) => ({ value: s, label: t(`sources.${s}`), description: t(`sourceHints.${s}`) }))}
              />
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t("fields.aggregate")}>
                <Select value={form.aggregate} onValueChange={(v) => set("aggregate", v as MetricAggregate)} options={AGGREGATES.map((a) => ({ value: a, label: t(`aggregates.${a}`) }))} />
              </Field>
              <Field label={t("fields.field")}>
                <Select
                  value={form.aggregate === "count" ? "" : fieldValue}
                  disabled={form.aggregate === "count"}
                  placeholder={t("fieldNotNeeded")}
                  onValueChange={(v) => set("field", v as MetricField)}
                  options={fields.map((f) => ({ value: f, label: t(`fieldNames.${f}`) }))}
                />
              </Field>
            </div>
            <fieldset className="grid gap-3 rounded-md border border-border p-3 sm:grid-cols-2">
              <legend className="px-1 text-sm font-medium">{t("filters")}</legend>
              {form.source === "spans" ? (
                <Field label={t("fields.kind")}>
                  <Select
                    value={form.kind}
                    onValueChange={(v) => set("kind", v)}
                    options={[{ value: ANY, label: t("anyKind") }, ...KINDS.map((k) => ({ value: k, label: t(`kinds.${k}`) }))]}
                  />
                </Field>
              ) : null}
              <Field label={form.source === "runs" ? t("fields.agent") : t("fields.name")} htmlFor="metric-f-name" hint={t("globHint")}>
                <Input id="metric-f-name" maxLength={200} placeholder={form.source === "runs" ? "soporte" : "buscar_*"} value={form.nameGlob} onChange={(e) => set("nameGlob", e.target.value)} />
              </Field>
              <Field label={t("fields.status")} htmlFor="metric-f-status">
                <Input id="metric-f-status" maxLength={20} placeholder="error" value={form.status} onChange={(e) => set("status", e.target.value.toLowerCase())} />
              </Field>
              <Field label={t("fields.model")} htmlFor="metric-f-model" hint={t("globHint")}>
                <Input id="metric-f-model" maxLength={200} placeholder="anthropic/claude-*" value={form.model} onChange={(e) => set("model", e.target.value)} />
              </Field>
              {form.source === "spans" ? (
                <Field label={t("fields.path")} htmlFor="metric-f-path" hint={t("globHint")}>
                  <Input id="metric-f-path" maxLength={500} placeholder="soporte.*" value={form.pathGlob} onChange={(e) => set("pathGlob", e.target.value)} />
                </Field>
              ) : null}
              <Field label={t("fields.output")} htmlFor="metric-f-output">
                <Input id="metric-f-output" maxLength={500} value={form.outputContains} onChange={(e) => set("outputContains", e.target.value)} />
              </Field>
              <Field label={t("fields.error")}>
                <Select
                  value={form.error}
                  onValueChange={(v) => set("error", v)}
                  options={[
                    { value: ANY, label: t("errorAny") },
                    { value: "yes", label: t("withErrors") },
                    { value: "no", label: t("withoutErrors") },
                  ]}
                />
              </Field>
            </fieldset>
          </div>
          <div className="flex min-w-0 flex-col gap-3">
            <PreviewPanel definition={{ ...definition, field: form.aggregate === "count" ? null : fieldValue }} enabled={open} />
            <div className="mt-auto flex justify-end gap-2">
              <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
                {tc("cancel")}
              </Button>
              <Button type="submit" variant="primary" loading={save.isPending} disabled={!valid}>
                {tc("save")}
              </Button>
            </div>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ValuesSheet({ metric, onOpenChange }: { metric: CustomMetric | null; onOpenChange: (o: boolean) => void }) {
  const t = useTranslations("analytics.metrics");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const [days, setDays] = React.useState("7");
  const [anchor] = React.useState(() => Date.now());
  const query = React.useMemo(() => {
    void anchor;
    return windowQuery(Number(days));
  }, [days, anchor]);
  const values = useQuery({
    queryKey: ["metrics", metric?.id ?? "", "values", query],
    queryFn: () => http.get<MetricValues>(`/metrics/${metric?.id}/values`, query),
    enabled: metric !== null,
    placeholderData: (prev) => prev,
  });
  return (
    <Sheet open={metric !== null} onOpenChange={onOpenChange} title={metric?.name ?? ""} description={metric?.description || t("valuesDescription")}>
      <div className="flex flex-col gap-4">
        <div className="w-44">
          <Select
            aria-label={t("period")}
            value={days}
            onValueChange={setDays}
            options={["1", "7", "30", "90"].map((d) => ({ value: d, label: t("lastDays", { days: Number(d) }) }))}
          />
        </div>
        {metric ? <DefinitionSummary definition={metric.definition} /> : null}
        {values.isLoading ? (
          <SkeletonRows rows={3} />
        ) : values.error ? (
          <ErrorState title={tc("errorTitle")} description={apiErrorText(values.error, tc("errorGeneric"))} onRetry={() => void values.refetch()} retryLabel={tc("retry")} />
        ) : values.data ? (
          <div className={values.isPlaceholderData ? "opacity-60" : undefined}>
            <p className="text-xs text-fg-subtle">{t("total")}</p>
            <p className="text-xl font-semibold text-fg">{formatMetric(values.data.total, values.data.unit, locale)}</p>
            <MetricValuesChart
              points={values.data.points}
              bucket={values.data.bucket}
              name={metric?.name ?? ""}
              additive={metric?.definition.aggregate === "count" || metric?.definition.aggregate === "sum"}
              format={(v) => formatMetric(v, values.data.unit, locale)}
            />
            <details className="mt-3 text-sm">
              <summary className="cursor-pointer text-xs text-fg-muted hover:text-fg">{t("showTable")}</summary>
              <table className="mt-2 w-full text-xs">
                <tbody>
                  {values.data.points.map((p) => (
                    <tr key={p.t} className="border-t border-border">
                      <td className="py-1 pr-3">{new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: values.data.bucket === "hour" ? "short" : undefined }).format(new Date(p.t))}</td>
                      <td className="tabular py-1 text-right">{formatMetric(p.value, values.data.unit, locale)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          </div>
        ) : null}
      </div>
    </Sheet>
  );
}

export function MetricsManager() {
  const t = useTranslations("analytics.metrics");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const isAdmin = useRole("admin");
  const metrics = useCustomMetrics();
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<CustomMetric | null>(null);
  const [deleting, setDeleting] = React.useState<CustomMetric | null>(null);
  const [viewing, setViewing] = React.useState<CustomMetric | null>(null);
  const remove = useMutation({
    mutationFn: (id: string) => http.del(`/metrics/${id}`),
    onSuccess: () => {
      setDeleting(null);
      toast.success(t("deleted"));
      void qc.invalidateQueries({ queryKey: analyticsKeys.metrics });
      void qc.invalidateQueries({ queryKey: analyticsKeys.alarmCatalog });
    },
    onError: (err) => {
      setDeleting(null);
      toast.error(apiErrorText(err, tc("errorGeneric")));
    },
  });
  const openNew = () => {
    setEditing(null);
    setDialogOpen(true);
  };
  const list = metrics.data ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-fg">{t("title")}</h2>
          <p className="mt-0.5 max-w-3xl text-sm text-fg-muted">{t("description")}</p>
        </div>
        {isAdmin ? (
          <Button variant="primary" onClick={openNew}>
            <Plus />
            {t("new")}
          </Button>
        ) : null}
      </div>
      <Card>
        {metrics.isLoading ? (
          <div className="p-4">
            <SkeletonRows rows={4} />
          </div>
        ) : metrics.error ? (
          <div className="p-4">
            <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void metrics.refetch()} retryLabel={tc("retry")} />
          </div>
        ) : list.length === 0 ? (
          <div className="p-4">
            <EmptyState
              icon={<Gauge />}
              title={t("emptyTitle")}
              description={t("emptyDescription")}
              action={
                isAdmin ? (
                  <Button variant="primary" onClick={openNew}>
                    <Plus />
                    {t("new")}
                  </Button>
                ) : null
              }
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <THead>
                <tr>
                  <TH>{tc("name")}</TH>
                  <TH>{t("columns.definition")}</TH>
                  <TH className="hidden md:table-cell">{t("columns.alarms")}</TH>
                  <TH className="w-56" />
                </tr>
              </THead>
              <TBody>
                {list.map((m) => (
                  <TR key={m.id}>
                    <TD className="max-w-[16rem]">
                      <span className="font-medium">{m.name}</span>
                      {m.description ? <span className="block truncate text-xs text-fg-muted">{m.description}</span> : null}
                      {!m.valid ? <Badge tone="danger">{t("invalid")}</Badge> : null}
                    </TD>
                    <TD>
                      <DefinitionSummary definition={m.definition} />
                    </TD>
                    <TD className="tabular hidden md:table-cell">{m.alarm_count}</TD>
                    <TD className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button variant="ghost" size="sm" onClick={() => setViewing(m)} disabled={!m.valid}>
                          <LineChart />
                          {t("values")}
                        </Button>
                        {isAdmin ? (
                          <>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => {
                                setEditing(m);
                                setDialogOpen(true);
                              }}
                            >
                              {tc("edit")}
                            </Button>
                            <Button variant="ghost" size="sm" onClick={() => setDeleting(m)}>
                              {tc("delete")}
                            </Button>
                          </>
                        ) : null}
                      </div>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </div>
        )}
      </Card>
      <MetricDialog open={dialogOpen} onOpenChange={setDialogOpen} editing={editing} />
      <ValuesSheet metric={viewing} onOpenChange={(o) => !o && setViewing(null)} />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={t("deleteTitle", { name: deleting?.name ?? "" })}
        description={deleting && deleting.alarm_count > 0 ? t("deleteInUse", { count: deleting.alarm_count }) : t("deleteDescription")}
        confirmLabel={tc("delete")}
        cancelLabel={tc("cancel")}
        loading={remove.isPending}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting.id);
        }}
      />
    </div>
  );
}
