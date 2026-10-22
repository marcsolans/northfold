"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  ConfirmDialog,
  Dialog,
  DialogContent,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Select,
  Sheet,
  SkeletonRows,
  Switch,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  toast,
} from "@messer/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, BellRing, CheckCircle2, History, PauseCircle, Plus, Siren } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { ApiError, http } from "@/lib/api";
import { formatDate, formatRelative, localeTag } from "@/lib/format";
import { useRole } from "@/lib/hooks/use-me";
import { useProjects } from "@/lib/studio/hooks";

import { formatMetric } from "./format";
import { analyticsKeys, useAlarmCatalog, useAlarmHistory, useAlarms } from "./queries";
import type { Alarm, AlarmTest, Comparator, DeliveryChannel, MetricUnit } from "./types";

const COMPARATORS: Comparator[] = [">", ">=", "<", "<=", "==", "!="];
const WINDOWS = [5, 15, 30, 60, 180, 360, 720, 1440];
const ORG = "__org__";
const ANY = "__any__";

function errorText(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    const errors = err.details.errors;
    if (Array.isArray(errors) && errors.length > 0) {
      const first = errors[0] as { msg?: string };
      if (first.msg) return first.msg.replace(/^Value error, /, "");
    }
    return err.message || fallback;
  }
  return fallback;
}

export function useMetricLabel() {
  const t = useTranslations("analytics.builtinMetrics");
  return React.useCallback(
    (metric: string, customName?: string | null) => {
      if (metric.startsWith("custom:")) return customName ?? metric;
      return t.has(metric) ? t(metric) : metric;
    },
    [t],
  );
}

function unitSuffix(unit: MetricUnit): string {
  return unit === "percent" ? "%" : unit === "ms" ? "ms" : unit === "usd" ? "USD" : "";
}

export function windowLabel(minutes: number, locale: string): string {
  if (minutes % 1440 === 0) return new Intl.NumberFormat(locale, { style: "unit", unit: "day", unitDisplay: "long" }).format(minutes / 1440);
  if (minutes % 60 === 0) return new Intl.NumberFormat(locale, { style: "unit", unit: "hour", unitDisplay: "long" }).format(minutes / 60);
  return new Intl.NumberFormat(locale, { style: "unit", unit: "minute", unitDisplay: "long" }).format(minutes);
}

function StateBadge({ alarm }: { alarm: Pick<Alarm, "state" | "enabled"> }) {
  const t = useTranslations("analytics.alarms.states");
  if (!alarm.enabled) {
    return (
      <Badge tone="neutral">
        <PauseCircle className="size-3" aria-hidden />
        {t("paused")}
      </Badge>
    );
  }
  return alarm.state === "firing" ? (
    <Badge tone="danger">
      <AlertTriangle className="size-3" aria-hidden />
      {t("firing")}
    </Badge>
  ) : (
    <Badge tone="success">
      <CheckCircle2 className="size-3" aria-hidden />
      {t("ok")}
    </Badge>
  );
}

interface FormState {
  name: string;
  metric: string;
  comparator: Comparator;
  threshold: string;
  window: string;
  project: string;
  environment: string;
  runChannel: string;
  agent: string;
  email: boolean;
  slack: boolean;
  slackChannel: string;
  enabled: boolean;
}

function initialForm(alarm: Alarm | null): FormState {
  return {
    name: alarm?.name ?? "",
    metric: alarm?.metric ?? "error_rate",
    comparator: alarm?.comparator ?? ">",
    threshold: alarm ? String(alarm.threshold) : "",
    window: String(alarm?.window_minutes ?? 60),
    project: alarm?.project_id ?? ORG,
    environment: alarm?.environment ?? ANY,
    runChannel: alarm?.run_channel ?? "",
    agent: alarm?.workforce_name ?? "",
    email: alarm ? alarm.channels.includes("email") : true,
    slack: alarm ? alarm.channels.includes("slack") : false,
    slackChannel: alarm?.slack_channel ?? "",
    enabled: alarm?.enabled ?? true,
  };
}

function AlarmDialog({ open, onOpenChange, editing }: { open: boolean; onOpenChange: (open: boolean) => void; editing: Alarm | null }) {
  const t = useTranslations("analytics.alarms");
  const ta = useTranslations("analytics");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const catalog = useAlarmCatalog();
  const projects = useProjects();
  const metricLabel = useMetricLabel();
  const [form, setForm] = React.useState<FormState>(() => initialForm(editing));
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (open) {
      setForm(initialForm(editing));
      setError(null);
    }
  }, [open, editing]);

  const metrics = [...(catalog.data?.builtin ?? []), ...(catalog.data?.custom ?? [])];
  const unit = metrics.find((m) => m.key === form.metric)?.unit ?? editing?.unit ?? "count";
  const thresholdValid = form.threshold.trim() !== "" && Number.isFinite(Number(form.threshold));
  const slackValid = !form.slack || form.slackChannel.trim().length > 0;
  const valid = form.name.trim().length > 0 && thresholdValid && slackValid;

  const save = useMutation({
    mutationFn: () => {
      const channels: DeliveryChannel[] = [...(form.email ? (["email"] as const) : []), ...(form.slack ? (["slack"] as const) : [])];
      const body = {
        name: form.name.trim(),
        metric: form.metric,
        comparator: form.comparator,
        threshold: Number(form.threshold),
        window_minutes: Number(form.window),
        project_id: form.project === ORG ? null : form.project,
        environment: form.environment === ANY ? null : form.environment,
        run_channel: form.runChannel.trim() || null,
        workforce_name: form.agent.trim() || null,
        channels,
        slack_channel: form.slackChannel.trim() || null,
        enabled: form.enabled,
      };
      return editing ? http.patch<Alarm>(`/alarms/${editing.id}`, body) : http.post<Alarm>("/alarms", body);
    },
    onSuccess: () => {
      toast.success(editing ? t("updated") : t("created"));
      onOpenChange(false);
      void qc.invalidateQueries({ queryKey: analyticsKeys.alarms });
    },
    onError: (err) => setError(errorText(err, tc("errorGeneric"))),
  });

  const metricOptions = metrics.map((m) => ({
    value: m.key,
    label: metricLabel(m.key, m.name),
    description: m.key.startsWith("custom:") ? t("customMetric") : undefined,
  }));
  const windowOptions = Array.from(new Set([...WINDOWS, Number(form.window)])).sort((a, b) => a - b);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent wide title={editing ? t("editTitle") : t("newTitle")} description={t("formDescription")}>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (valid) save.mutate();
          }}
        >
          {error ? <Alert tone="danger">{error}</Alert> : null}
          <Field label={t("fields.name")} htmlFor="alarm-name">
            <Input id="alarm-name" required autoFocus maxLength={200} value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
          </Field>
          <div className="grid gap-3 sm:grid-cols-[1fr_6rem_9rem]">
            <Field label={t("fields.metric")}>
              <Select value={form.metric} onValueChange={(metric) => setForm((f) => ({ ...f, metric }))} options={metricOptions} disabled={catalog.isLoading} />
            </Field>
            <Field label={t("fields.comparator")}>
              <Select
                value={form.comparator}
                onValueChange={(c) => setForm((f) => ({ ...f, comparator: c as Comparator }))}
                options={COMPARATORS.map((c) => ({ value: c, label: c }))}
              />
            </Field>
            <Field
              label={unitSuffix(unit) ? t("fields.thresholdUnit", { unit: unitSuffix(unit) }) : t("fields.threshold")}
              htmlFor="alarm-threshold"
              error={form.threshold !== "" && !thresholdValid ? t("thresholdInvalid") : undefined}
            >
              <Input
                id="alarm-threshold"
                type="number"
                step="any"
                inputMode="decimal"
                required
                value={form.threshold}
                onChange={(e) => setForm((f) => ({ ...f, threshold: e.target.value }))}
              />
            </Field>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("fields.window")} hint={t("windowHint")}>
              <Select
                value={form.window}
                onValueChange={(w) => setForm((f) => ({ ...f, window: w }))}
                options={windowOptions.map((w) => ({ value: String(w), label: windowLabel(w, locale) }))}
              />
            </Field>
            <Field label={t("fields.project")}>
              <Select
                value={form.project}
                onValueChange={(project) => setForm((f) => ({ ...f, project }))}
                options={[{ value: ORG, label: t("orgWide") }, ...(projects.data ?? []).map((p) => ({ value: p.id, label: p.name }))]}
              />
            </Field>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label={t("fields.environment")}>
              <Select
                value={form.environment}
                onValueChange={(environment) => setForm((f) => ({ ...f, environment }))}
                options={[
                  { value: ANY, label: t("anyEnvironment") },
                  { value: "production", label: ta("environments.production") },
                  { value: "development", label: ta("environments.development") },
                ]}
              />
            </Field>
            <Field label={t("fields.agent")} htmlFor="alarm-agent" hint={tc("optional")}>
              <Input id="alarm-agent" maxLength={80} value={form.agent} onChange={(e) => setForm((f) => ({ ...f, agent: e.target.value }))} />
            </Field>
            <Field label={t("fields.runChannel")} htmlFor="alarm-run-channel" hint={tc("optional")}>
              <Input
                id="alarm-run-channel"
                maxLength={20}
                placeholder="whatsapp"
                value={form.runChannel}
                onChange={(e) => setForm((f) => ({ ...f, runChannel: e.target.value }))}
              />
            </Field>
          </div>
          <fieldset className="flex flex-col gap-2 rounded-md border border-border p-3">
            <legend className="px-1 text-sm font-medium">{t("fields.channels")}</legend>
            <p className="text-xs text-fg-muted">{t("inAppAlways")}</p>
            <label className="flex items-center gap-2 text-sm">
              <Checkbox checked={form.email} onCheckedChange={(v) => setForm((f) => ({ ...f, email: v === true }))} />
              {t("channels.email")}
            </label>
            <label className="flex items-center gap-2 text-sm">
              <Checkbox checked={form.slack} onCheckedChange={(v) => setForm((f) => ({ ...f, slack: v === true }))} />
              {t("channels.slack")}
            </label>
            {form.slack ? (
              <>
                <Field
                  label={t("fields.slackChannel")}
                  htmlFor="alarm-slack-channel"
                  error={!slackValid ? t("slackChannelRequired") : undefined}
                >
                  <Input
                    id="alarm-slack-channel"
                    placeholder="#alertas"
                    maxLength={80}
                    value={form.slackChannel}
                    onChange={(e) => setForm((f) => ({ ...f, slackChannel: e.target.value }))}
                  />
                </Field>
                {catalog.data && !catalog.data.slack_connected ? (
                  <Alert tone="warning">
                    {t("slackNotConnected")}{" "}
                    <Link href="/app/connectors" className="font-medium underline underline-offset-2">
                      {t("connectSlack")}
                    </Link>
                  </Alert>
                ) : null}
              </>
            ) : null}
          </fieldset>
          <label className="flex items-center gap-3 text-sm">
            <Switch checked={form.enabled} onCheckedChange={(enabled) => setForm((f) => ({ ...f, enabled }))} aria-label={t("fields.enabled")} />
            {t("fields.enabled")}
          </label>
          <div className="mt-2 flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
              {tc("cancel")}
            </Button>
            <Button type="submit" variant="primary" loading={save.isPending} disabled={!valid}>
              {tc("save")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function HistorySheet({ alarm, onOpenChange }: { alarm: Alarm | null; onOpenChange: (open: boolean) => void }) {
  const t = useTranslations("analytics.alarms");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const history = useAlarmHistory(alarm?.id ?? null);
  const deliveryText = (d: { in_app?: number; email?: number; slack?: string }) => {
    const parts: string[] = [];
    if (d.in_app) parts.push(t("delivery.inApp", { count: d.in_app }));
    if (d.email) parts.push(t("delivery.email", { count: d.email }));
    if (d.slack) {
      const [status, code] = d.slack.split(":");
      const key = `delivery.slack.${status}`;
      const reasonKey = `delivery.reasons.${code ?? ""}`;
      const reason = code ? (t.has(reasonKey) ? t(reasonKey) : code) : "";
      parts.push(t.has(key) ? t(key, { reason }) : d.slack);
    }
    return parts.join(" · ");
  };
  return (
    <Sheet open={alarm !== null} onOpenChange={onOpenChange} title={t("historyTitle", { name: alarm?.name ?? "" })} description={t("historyDescription")}>
      {history.isLoading ? (
        <SkeletonRows rows={4} />
      ) : history.error ? (
        <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void history.refetch()} retryLabel={tc("retry")} />
      ) : !history.data || history.data.length === 0 ? (
        <EmptyState icon={<History />} title={t("historyEmptyTitle")} description={t("historyEmptyDescription")} />
      ) : (
        <ol className="flex flex-col divide-y divide-border">
          {history.data.map((e) => (
            <li key={e.id} className="flex flex-col gap-1 py-3">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <StateBadge alarm={{ state: e.from_state, enabled: true }} />
                <ArrowRight className="size-3.5 text-fg-subtle" aria-label={t("transitionTo")} />
                <StateBadge alarm={{ state: e.to_state, enabled: true }} />
                <span className="ml-auto text-xs text-fg-subtle">{formatDate(e.created_at, locale, true)}</span>
              </div>
              <p className="text-sm text-fg">
                {t("eventValue", {
                  value: formatMetric(e.value, alarm?.unit ?? "count", locale),
                  comparator: e.comparator,
                  threshold: formatMetric(e.threshold, alarm?.unit ?? "count", locale),
                  window: windowLabel(e.window_minutes, locale),
                })}
              </p>
              <p className="text-xs text-fg-muted">{deliveryText(e.delivery)}</p>
            </li>
          ))}
        </ol>
      )}
    </Sheet>
  );
}

export function AlarmsManager() {
  const t = useTranslations("analytics.alarms");
  const ta = useTranslations("analytics");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const isAdmin = useRole("admin");
  const alarms = useAlarms();
  const catalog = useAlarmCatalog();
  const metricLabel = useMetricLabel();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<Alarm | null>(null);
  const [deleting, setDeleting] = React.useState<Alarm | null>(null);
  const historyId = params.get("alarm");
  const historyAlarm = alarms.data?.find((a) => a.id === historyId) ?? null;

  const openHistory = (id: string | null) => {
    const next = new URLSearchParams(params.toString());
    if (id) next.set("alarm", id);
    else next.delete("alarm");
    const qs = next.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  };

  const invalidate = () => void qc.invalidateQueries({ queryKey: analyticsKeys.alarms });
  const toggle = useMutation({
    mutationFn: (a: Alarm) => http.patch<Alarm>(`/alarms/${a.id}`, { enabled: !a.enabled }),
    onSuccess: (a) => {
      toast.success(a.enabled ? t("enabledToast") : t("pausedToast"));
      invalidate();
    },
    onError: (err) => toast.error(errorText(err, tc("errorGeneric"))),
  });
  const remove = useMutation({
    mutationFn: (id: string) => http.del(`/alarms/${id}`),
    onSuccess: () => {
      setDeleting(null);
      toast.success(t("deleted"));
      invalidate();
    },
    onError: (err) => toast.error(errorText(err, tc("errorGeneric"))),
  });
  const test = useMutation({
    mutationFn: (a: Alarm) => http.post<AlarmTest>(`/alarms/${a.id}/test`),
    onSuccess: (r, a) => {
      const value = formatMetric(r.value, r.unit, locale);
      if (r.error) toast.error(t(`testErrors.${r.error === "unknown_metric" ? "unknown_metric" : "invalid_metric"}`));
      else if (r.breached) toast.warning(t("testBreached", { name: a.name, value }));
      else toast.success(t("testOk", { name: a.name, value }));
    },
    onError: (err) => toast.error(errorText(err, tc("errorGeneric"))),
  });

  const openNew = () => {
    setEditing(null);
    setDialogOpen(true);
  };
  const list = alarms.data ?? [];
  const firing = list.filter((a) => a.enabled && a.state === "firing").length;

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
      {firing > 0 ? (
        <Alert tone="danger" title={t("firingBanner", { count: firing })}>
          {t("firingBannerHint")}
        </Alert>
      ) : null}
      <Card>
        {alarms.isLoading ? (
          <div className="p-4">
            <SkeletonRows rows={4} />
          </div>
        ) : alarms.error ? (
          <div className="p-4">
            <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void alarms.refetch()} retryLabel={tc("retry")} />
          </div>
        ) : list.length === 0 ? (
          <div className="p-4">
            <EmptyState
              icon={<Siren />}
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
                  <TH>{tc("status")}</TH>
                  <TH>{tc("name")}</TH>
                  <TH>{t("columns.condition")}</TH>
                  <TH className="hidden md:table-cell">{t("columns.lastValue")}</TH>
                  <TH className="hidden lg:table-cell">{t("columns.channels")}</TH>
                  <TH className="w-56" />
                </tr>
              </THead>
              <TBody>
                {list.map((a) => (
                  <TR key={a.id}>
                    <TD>
                      <StateBadge alarm={a} />
                    </TD>
                    <TD>
                      <span className="font-medium">{a.name}</span>
                      <span className="block text-xs text-fg-muted">
                        {[
                          a.project_name ?? t("orgWide"),
                          a.environment ? ta(`environments.${a.environment}`) : null,
                          a.workforce_name,
                          a.run_channel,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                    </TD>
                    <TD>
                      <span>
                        {metricLabel(a.metric, a.metric_name)}{" "}
                        <span className="whitespace-nowrap">
                          {a.comparator} {formatMetric(a.threshold, a.unit, locale)}
                        </span>
                      </span>
                      <span className="block text-xs text-fg-muted">{t("windowShort", { window: windowLabel(a.window_minutes, locale) })}</span>
                    </TD>
                    <TD className="hidden md:table-cell">
                      <span className="tabular">{a.last_evaluated_at ? formatMetric(a.last_value, a.unit, locale) : "—"}</span>
                      <span className="block text-xs text-fg-subtle">
                        {a.last_evaluated_at ? t("evaluated", { when: formatRelative(a.last_evaluated_at, locale) }) : t("neverEvaluated")}
                      </span>
                    </TD>
                    <TD className="hidden lg:table-cell">
                      <span className="flex flex-wrap gap-1">
                        <Badge tone="outline">{t("channels.inApp")}</Badge>
                        {a.channels.map((c) => (
                          <Badge key={c} tone="outline">
                            {c === "slack" && a.slack_channel ? `Slack ${a.slack_channel}` : t(`channels.${c}Short`)}
                          </Badge>
                        ))}
                      </span>
                    </TD>
                    <TD className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        {isAdmin ? (
                          <Switch
                            checked={a.enabled}
                            disabled={toggle.isPending}
                            onCheckedChange={() => toggle.mutate(a)}
                            aria-label={a.enabled ? t("pause") : t("enable")}
                          />
                        ) : null}
                        <Button variant="ghost" size="sm" onClick={() => test.mutate(a)} loading={test.isPending && test.variables?.id === a.id}>
                          <BellRing />
                          {t("test")}
                        </Button>
                        <Button variant="ghost" size="icon-sm" onClick={() => openHistory(a.id)} aria-label={t("history")}>
                          <History />
                        </Button>
                        {isAdmin ? (
                          <>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => {
                                setEditing(a);
                                setDialogOpen(true);
                              }}
                            >
                              {tc("edit")}
                            </Button>
                            <Button variant="ghost" size="sm" onClick={() => setDeleting(a)}>
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
      <p className="text-xs text-fg-subtle">{t("footnote")}</p>
      {catalog.data && !catalog.data.slack_connected && list.some((a) => a.channels.includes("slack")) ? (
        <Alert tone="warning">{t("slackNotConnected")}</Alert>
      ) : null}

      <AlarmDialog open={dialogOpen} onOpenChange={setDialogOpen} editing={editing} />
      <HistorySheet alarm={historyAlarm} onOpenChange={(open) => !open && openHistory(null)} />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={t("deleteTitle", { name: deleting?.name ?? "" })}
        description={t("deleteDescription")}
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
