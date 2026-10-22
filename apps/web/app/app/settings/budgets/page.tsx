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
  PageHeader,
  Select,
  SkeletonRows,
  Switch,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  cn,
  toast,
} from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Wallet } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { type Budget, type BudgetPeriod, errorText, formatUtcDate, inclusiveEnd, useUpgradeDialog } from "@/components/billing";
import { ApiError, http } from "@/lib/api";
import { formatUsd, localeTag } from "@/lib/format";
import { useRole } from "@/lib/hooks/use-me";

const BUDGETS_KEY = ["budgets"] as const;
const ORG_SCOPE = "__org__";
const STATE_TONE = { ok: "success", alert: "warning", exceeded: "danger" } as const;

interface ProjectLite {
  id: string;
  name: string;
}

interface FormState {
  scope: string;
  period: BudgetPeriod;
  limit: string;
  threshold: string;
  hardStop: boolean;
}

function SpendBar({ budget }: { budget: Budget }) {
  const pct = Math.min(100, budget.pct);
  return (
    <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-muted" aria-hidden>
      <div
        className={cn(
          "h-full rounded-full",
          budget.state === "exceeded" ? "bg-danger" : budget.state === "alert" ? "bg-warning" : "bg-fg",
        )}
        style={{ width: `${pct}%` }}
      />
      <div className="absolute inset-y-0 w-px bg-fg-subtle" style={{ left: `${budget.alert_threshold_pct}%` }} />
    </div>
  );
}

function BudgetDialog({
  open,
  onOpenChange,
  editing,
  projects,
  takenScopes,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  editing: Budget | null;
  projects: ProjectLite[];
  takenScopes: Set<string>;
}) {
  const t = useTranslations("billing");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const upgrade = useUpgradeDialog();
  const initial = React.useCallback(
    (): FormState => ({
      scope: editing ? (editing.project_id ?? ORG_SCOPE) : takenScopes.has(ORG_SCOPE) ? (projects.find((p) => !takenScopes.has(p.id))?.id ?? ORG_SCOPE) : ORG_SCOPE,
      period: editing?.period ?? "month",
      limit: editing ? String(Number(editing.limit_usd)) : "",
      threshold: String(editing?.alert_threshold_pct ?? 80),
      hardStop: editing?.hard_stop ?? true,
    }),
    [editing, projects, takenScopes],
  );
  const [form, setForm] = React.useState<FormState>(initial);
  const [error, setError] = React.useState<string | null>(null);
  const initialRef = React.useRef(initial);
  initialRef.current = initial;
  // Reset the form each time the dialog opens (not on every parent re-render).
  React.useEffect(() => {
    if (open) {
      setForm(initialRef.current());
      setError(null);
    }
  }, [open, editing]);

  const save = useMutation({
    mutationFn: () => {
      const body = {
        period: form.period,
        limit_usd: Number(form.limit).toFixed(2),
        alert_threshold_pct: Math.round(Number(form.threshold)),
        hard_stop: form.hardStop,
      };
      return editing
        ? http.patch<Budget>(`/budgets/${editing.id}`, body)
        : http.post<Budget>("/budgets", { ...body, project_id: form.scope === ORG_SCOPE ? null : form.scope });
    },
    onSuccess: () => {
      toast.success(editing ? t("budgets.updated") : t("budgets.created"));
      onOpenChange(false);
      void qc.invalidateQueries({ queryKey: BUDGETS_KEY });
    },
    onError: (err) => {
      if (!upgrade.handle(err)) setError(err instanceof ApiError ? err.message : String(err));
    },
  });

  const limitValid = Number(form.limit) > 0;
  const thresholdValid = Number(form.threshold) >= 1 && Number(form.threshold) <= 100;
  const scopeOptions = [
    { value: ORG_SCOPE, label: t("budgets.orgScope"), disabled: !editing && takenScopes.has(ORG_SCOPE) },
    ...projects.map((p) => ({ value: p.id, label: p.name, disabled: !editing && takenScopes.has(p.id) })),
  ];

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent title={editing ? t("budgets.editTitle") : t("budgets.newTitle")} description={t("budgets.formDescription")}>
          <form
            className="flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (limitValid && thresholdValid) save.mutate();
            }}
          >
            {error ? <Alert tone="danger">{error}</Alert> : null}
            <Field label={t("budgets.scope")}>
              <Select
                value={form.scope}
                disabled={Boolean(editing)}
                onValueChange={(scope) => setForm((f) => ({ ...f, scope }))}
                options={scopeOptions}
              />
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t("budgets.period")}>
                <Select
                  value={form.period}
                  onValueChange={(period) => setForm((f) => ({ ...f, period: period as BudgetPeriod }))}
                  options={(["month", "week", "day"] as const).map((p) => ({ value: p, label: t(`budgets.periods.${p}`) }))}
                />
              </Field>
              <Field
                label={t("budgets.limit")}
                htmlFor="budget-limit"
                error={form.limit !== "" && !limitValid ? t("budgets.limitInvalid") : undefined}
              >
                <Input
                  id="budget-limit"
                  type="number"
                  min={0.01}
                  step={0.01}
                  inputMode="decimal"
                  required
                  autoFocus
                  value={form.limit}
                  onChange={(e) => setForm((f) => ({ ...f, limit: e.target.value }))}
                />
              </Field>
            </div>
            <Field
              label={t("budgets.threshold")}
              htmlFor="budget-threshold"
              hint={t("budgets.thresholdHint")}
              error={!thresholdValid ? t("budgets.thresholdInvalid") : undefined}
            >
              <Input
                id="budget-threshold"
                type="number"
                min={1}
                max={100}
                step={1}
                value={form.threshold}
                onChange={(e) => setForm((f) => ({ ...f, threshold: e.target.value }))}
              />
            </Field>
            <label className="flex items-start gap-3 text-sm">
              <Switch
                checked={form.hardStop}
                onCheckedChange={(hardStop) => setForm((f) => ({ ...f, hardStop }))}
                aria-label={t("budgets.hardStop")}
              />
              <span>
                <span className="font-medium">{t("budgets.hardStop")}</span>
                <span className="block text-xs text-fg-muted">{t("budgets.hardStopHint")}</span>
              </span>
            </label>
            <div className="mt-2 flex justify-end gap-2">
              <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
                {tc("cancel")}
              </Button>
              <Button type="submit" variant="primary" loading={save.isPending} disabled={!limitValid || !thresholdValid}>
                {tc("save")}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
      {upgrade.dialog}
    </>
  );
}

export default function BudgetsSettingsPage() {
  const t = useTranslations("billing");
  const ts = useTranslations("settings.sections");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const isAdmin = useRole("admin");
  const budgets = useQuery({ queryKey: BUDGETS_KEY, queryFn: () => http.get<Budget[]>("/budgets") });
  const projects = useQuery({ queryKey: ["projects", "lite"], queryFn: () => http.get<ProjectLite[]>("/projects") });
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<Budget | null>(null);
  const [deleting, setDeleting] = React.useState<Budget | null>(null);

  const remove = useMutation({
    mutationFn: (id: string) => http.del(`/budgets/${id}`),
    onSuccess: () => {
      setDeleting(null);
      toast.success(t("budgets.deleted"));
      void qc.invalidateQueries({ queryKey: BUDGETS_KEY });
    },
    onError: (err) => toast.error(errorText(err)),
  });

  const list = budgets.data ?? [];
  const takenScopes = new Set(list.map((b) => b.project_id ?? ORG_SCOPE));
  const projectList = projects.data ?? [];
  const allTaken = takenScopes.has(ORG_SCOPE) && projectList.every((p) => takenScopes.has(p.id));
  const openNew = () => {
    setEditing(null);
    setDialogOpen(true);
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={ts("budgets")}
        description={t("budgets.description")}
        actions={
          isAdmin ? (
            <Button variant="primary" onClick={openNew} disabled={budgets.isLoading || allTaken}>
              <Plus />
              {t("budgets.new")}
            </Button>
          ) : null
        }
      />
      <Card>
        {budgets.isLoading ? (
          <div className="p-4">
            <SkeletonRows rows={3} />
          </div>
        ) : budgets.error ? (
          <div className="p-4">
            <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void budgets.refetch()} />
          </div>
        ) : list.length === 0 ? (
          <div className="p-4">
            <EmptyState
              icon={<Wallet />}
              title={t("budgets.emptyTitle")}
              description={t("budgets.emptyDescription")}
              action={
                isAdmin ? (
                  <Button variant="primary" onClick={openNew}>
                    <Plus />
                    {t("budgets.new")}
                  </Button>
                ) : null
              }
            />
          </div>
        ) : (
          <Table>
            <THead>
              <tr>
                <TH>{t("budgets.scope")}</TH>
                <TH className="hidden sm:table-cell">{t("budgets.period")}</TH>
                <TH className="w-1/3">{t("budgets.spend")}</TH>
                <TH>{tc("status")}</TH>
                <TH className="w-32" />
              </tr>
            </THead>
            <TBody>
              {list.map((b) => (
                <TR key={b.id}>
                  <TD>
                    <span className="font-medium">{b.project_name ?? t("budgets.orgScope")}</span>
                    <span className="mt-0.5 flex flex-wrap gap-1">
                      {b.hard_stop ? <Badge tone="outline">{t("budgets.hardStopBadge")}</Badge> : null}
                      <Badge tone="outline">{t("budgets.alertAt", { pct: b.alert_threshold_pct })}</Badge>
                    </span>
                  </TD>
                  <TD className="hidden text-fg-muted sm:table-cell">
                    {t(`budgets.periods.${b.period}`)}
                    <span className="block text-xs text-fg-subtle">
                      {formatUtcDate(b.period_start, locale)} – {formatUtcDate(inclusiveEnd(b.period_end), locale)}
                    </span>
                  </TD>
                  <TD>
                    <div className="flex flex-col gap-1.5">
                      <span className="tabular text-sm">
                        {formatUsd(b.spent_usd, locale)} <span className="text-fg-subtle">/ {formatUsd(b.limit_usd, locale)}</span>
                        <span className="ml-2 text-xs text-fg-muted">{b.pct}%</span>
                      </span>
                      <SpendBar budget={b} />
                    </div>
                  </TD>
                  <TD>
                    <Badge tone={STATE_TONE[b.state]}>{t(`budgets.states.${b.state}`)}</Badge>
                  </TD>
                  <TD className="text-right">
                    {isAdmin ? (
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            setEditing(b);
                            setDialogOpen(true);
                          }}
                        >
                          {tc("edit")}
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => setDeleting(b)}>
                          {tc("delete")}
                        </Button>
                      </div>
                    ) : null}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
      <p className="text-xs text-fg-subtle">{t("budgets.footnote")}</p>

      <BudgetDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        editing={editing}
        projects={projectList}
        takenScopes={takenScopes}
      />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={t("budgets.deleteTitle", { scope: deleting?.project_name ?? t("budgets.orgScope") })}
        description={t("budgets.deleteDescription")}
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
