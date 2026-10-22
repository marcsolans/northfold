"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Dialog,
  DialogContent,
  ErrorState,
  Field,
  Input,
  PageHeader,
  SkeletonRows,
  Switch,
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
import { Plus, RefreshCw } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { ADMIN_KEY, type AdminPlan, type StripeSync } from "@/components/admin/types";
import { FEATURE_KEYS, LIMIT_KEYS, type LimitKey, PLANS_KEY, errorText } from "@/components/billing";
import { ApiError, http } from "@/lib/api";
import { formatEur, formatNumber, localeTag } from "@/lib/format";

const PLANS_ADMIN_KEY = [...ADMIN_KEY, "plans"] as const;

interface PlanForm {
  id: string;
  name: string;
  description: string;
  price_month_eur: string;
  price_year_eur: string;
  price_is_starting: boolean;
  public: boolean;
  self_serve: boolean;
  sort_order: string;
  limits: Record<LimitKey, string>;
  features: string[];
}

function toForm(plan: AdminPlan | null): PlanForm {
  return {
    id: plan?.id ?? "",
    name: plan?.name ?? "",
    description: plan?.description ?? "",
    price_month_eur: plan ? String(Number(plan.price_month_eur)) : "",
    price_year_eur: plan ? String(Number(plan.price_year_eur)) : "",
    price_is_starting: plan?.price_is_starting ?? false,
    public: plan?.public ?? true,
    self_serve: plan?.self_serve ?? true,
    sort_order: String(plan?.sort_order ?? 10),
    limits: Object.fromEntries(LIMIT_KEYS.map((k) => [k, String(plan?.limits[k] ?? 0)])) as Record<LimitKey, string>,
    features: plan?.limits.features ?? [],
  };
}

function syncMessage(sync: StripeSync | null, t: (key: string, values?: Record<string, string>) => string): string | null {
  if (!sync) return null;
  if (sync.mode !== "stripe") return t("plans.syncSimulated");
  if (!sync.ok) return t("plans.syncFailed", { error: sync.error ?? "" });
  return sync.changed ? t("plans.syncChanged") : t("plans.syncUnchanged");
}

function PlanDialog({ plan, open, onOpenChange }: { plan: AdminPlan | null; open: boolean; onOpenChange: (o: boolean) => void }) {
  const t = useTranslations("admin");
  const tb = useTranslations("billing");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const [form, setForm] = React.useState<PlanForm>(() => toForm(plan));
  const [error, setError] = React.useState<string | null>(null);
  const set = <K extends keyof PlanForm>(key: K, value: PlanForm[K]) => setForm((f) => ({ ...f, [key]: value }));
  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: form.name.trim(),
        description: form.description.trim(),
        price_month_eur: Number(form.price_month_eur).toFixed(2),
        price_year_eur: Number(form.price_year_eur).toFixed(2),
        price_is_starting: form.price_is_starting,
        public: form.public,
        self_serve: form.self_serve,
        sort_order: Math.round(Number(form.sort_order) || 0),
        limits: {
          ...Object.fromEntries(LIMIT_KEYS.map((k) => [k, Math.round(Number(form.limits[k]))])),
          features: form.features,
        },
      };
      return plan ? http.patch<AdminPlan>(`/admin/plans/${plan.id}`, body) : http.post<AdminPlan>("/admin/plans", { ...body, id: form.id.trim() });
    },
    onSuccess: (saved) => {
      const message = syncMessage(saved.stripe_sync, t);
      toast.success(plan ? t("plans.saved") : t("plans.created"), message ? { description: message } : undefined);
      onOpenChange(false);
      void qc.invalidateQueries({ queryKey: PLANS_ADMIN_KEY });
      void qc.invalidateQueries({ queryKey: PLANS_KEY });
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });
  const valid =
    form.name.trim() !== "" &&
    (plan !== null || /^[a-z0-9][a-z0-9_-]{1,38}$/.test(form.id.trim())) &&
    Number(form.price_month_eur) >= 0 &&
    form.price_month_eur !== "" &&
    Number(form.price_year_eur) >= 0 &&
    form.price_year_eur !== "" &&
    LIMIT_KEYS.every((k) => form.limits[k] !== "" && Number(form.limits[k]) >= -1);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent wide title={plan ? t("plans.editTitle", { plan: plan.name }) : t("plans.newTitle")} description={t("plans.formDescription")}>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            setError(null);
            if (valid) save.mutate();
          }}
        >
          {error ? <Alert tone="danger">{error}</Alert> : null}
          {plan && plan.subscriptions > 0 ? <Alert tone="info">{t("plans.liveWarning", { count: plan.subscriptions })}</Alert> : null}
          <div className="grid gap-3 sm:grid-cols-3">
            {!plan ? (
              <Field label={t("plans.id")} htmlFor="plan-id" hint={t("plans.idHint")}>
                <Input id="plan-id" required value={form.id} onChange={(e) => set("id", e.target.value)} />
              </Field>
            ) : null}
            <Field label={tc("name")} htmlFor="plan-name">
              <Input id="plan-name" required value={form.name} onChange={(e) => set("name", e.target.value)} />
            </Field>
            <Field label={t("plans.sortOrder")} htmlFor="plan-sort">
              <Input id="plan-sort" type="number" min={0} value={form.sort_order} onChange={(e) => set("sort_order", e.target.value)} />
            </Field>
          </div>
          <Field label={tc("description")} htmlFor="plan-description">
            <Textarea id="plan-description" value={form.description} onChange={(e) => set("description", e.target.value)} />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("plans.priceMonth")} htmlFor="plan-month">
              <Input id="plan-month" type="number" min={0} step={0.01} required value={form.price_month_eur} onChange={(e) => set("price_month_eur", e.target.value)} />
            </Field>
            <Field label={t("plans.priceYear")} htmlFor="plan-year" hint={t("plans.priceYearHint")}>
              <Input id="plan-year" type="number" min={0} step={0.01} required value={form.price_year_eur} onChange={(e) => set("price_year_eur", e.target.value)} />
            </Field>
          </div>
          <div className="flex flex-wrap gap-5 text-sm">
            {(
              [
                ["public", t("plans.public")],
                ["self_serve", t("plans.selfServe")],
                ["price_is_starting", t("plans.startingPrice")],
              ] as const
            ).map(([key, label]) => (
              <label key={key} className="flex items-center gap-2">
                <Switch checked={form[key]} onCheckedChange={(v) => set(key, v)} aria-label={label} />
                {label}
              </label>
            ))}
          </div>
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-sm font-medium">{t("plans.limits")}</legend>
            <p className="text-xs text-fg-subtle">{t("plans.limitsHint")}</p>
            <div className="grid gap-3 sm:grid-cols-5">
              {LIMIT_KEYS.map((k) => (
                <Field key={k} label={t(`plans.limitFields.${k}`)} htmlFor={`limit-${k}`}>
                  <Input
                    id={`limit-${k}`}
                    type="number"
                    min={-1}
                    step={1}
                    value={form.limits[k]}
                    onChange={(e) => setForm((f) => ({ ...f, limits: { ...f.limits, [k]: e.target.value } }))}
                  />
                </Field>
              ))}
            </div>
          </fieldset>
          <fieldset>
            <legend className="mb-2 text-sm font-medium">{t("plans.features")}</legend>
            <div className="grid gap-2 sm:grid-cols-3">
              {FEATURE_KEYS.map((f) => (
                <label key={f} className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={form.features.includes(f)}
                    onCheckedChange={(checked) =>
                      set("features", checked === true ? [...form.features, f] : form.features.filter((x) => x !== f))
                    }
                  />
                  {tb(`features.${f}`)}
                </label>
              ))}
            </div>
          </fieldset>
          <div className="flex justify-end gap-2">
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

export default function AdminPlansPage() {
  const t = useTranslations("admin");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const plans = useQuery({ queryKey: PLANS_ADMIN_KEY, queryFn: () => http.get<AdminPlan[]>("/admin/plans") });
  const [editing, setEditing] = React.useState<AdminPlan | null>(null);
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const sync = useMutation({
    mutationFn: () => http.post<AdminPlan[]>("/admin/plans/sync"),
    onSuccess: (rows) => {
      qc.setQueryData(PLANS_ADMIN_KEY, rows);
      const failed = rows.filter((r) => r.stripe_sync && !r.stripe_sync.ok);
      if (failed.length) toast.error(t("plans.syncSomeFailed", { plans: failed.map((r) => r.name).join(", ") }));
      else toast.success(syncMessage(rows[0]?.stripe_sync ?? null, t) ?? t("plans.syncUnchanged"));
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const fmtLimit = (v: number) => (v === -1 ? "∞" : formatNumber(v, locale));

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title={t("plans.title")}
        description={t("plans.description")}
        actions={
          <>
            <Button onClick={() => sync.mutate()} loading={sync.isPending}>
              <RefreshCw />
              {t("plans.sync")}
            </Button>
            <Button
              variant="primary"
              onClick={() => {
                setEditing(null);
                setDialogOpen(true);
              }}
            >
              <Plus />
              {t("plans.new")}
            </Button>
          </>
        }
      />
      <Card>
        {plans.isLoading ? (
          <div className="p-4">
            <SkeletonRows rows={4} />
          </div>
        ) : plans.error || !plans.data ? (
          <div className="p-4">
            <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void plans.refetch()} />
          </div>
        ) : (
          <Table>
            <THead>
              <tr>
                <TH>{t("plans.plan")}</TH>
                <TH className="text-right">{t("plans.priceMonth")}</TH>
                <TH className="hidden text-right sm:table-cell">{t("plans.priceYear")}</TH>
                <TH className="hidden lg:table-cell">{t("plans.limits")}</TH>
                <TH className="hidden xl:table-cell">{t("plans.stripe")}</TH>
                <TH className="text-right">{t("plans.subscriptions")}</TH>
                <TH className="w-20" />
              </tr>
            </THead>
            <TBody>
              {plans.data.map((p) => (
                <TR key={p.id}>
                  <TD>
                    <span className="font-medium">{p.name}</span>
                    <span className="ml-2 font-mono text-xs text-fg-subtle">{p.id}</span>
                    <span className="mt-0.5 flex flex-wrap gap-1">
                      {!p.public ? <Badge tone="outline">{t("plans.private")}</Badge> : null}
                      {!p.self_serve ? <Badge tone="outline">{t("plans.salesLed")}</Badge> : null}
                      {p.price_is_starting ? <Badge tone="outline">{t("plans.startingPrice")}</Badge> : null}
                    </span>
                  </TD>
                  <TD className="tabular text-right">{formatEur(p.price_month_eur, locale, 2)}</TD>
                  <TD className="tabular hidden text-right sm:table-cell">{formatEur(p.price_year_eur, locale, 2)}</TD>
                  <TD className="tabular hidden text-xs text-fg-muted lg:table-cell">
                    {t("plans.limitsSummary", {
                      seats: fmtLimit(p.limits.seats),
                      projects: fmtLimit(p.limits.projects),
                      runs: fmtLimit(p.limits.runs_month),
                      credits: fmtLimit(p.limits.credits_month),
                      storage: fmtLimit(p.limits.storage_gb),
                    })}
                    <span className="block">{t("plans.featureCount", { count: p.limits.features.length })}</span>
                  </TD>
                  <TD className="hidden font-mono text-xs text-fg-muted xl:table-cell">
                    {p.stripe_product_id ?? "—"}
                    {Object.entries(p.stripe_price_ids).map(([interval, id]) => (
                      <span key={interval} className="block">
                        {interval}: {id}
                      </span>
                    ))}
                    {p.stripe_sync && !p.stripe_sync.ok ? <span className="block text-danger">{p.stripe_sync.error}</span> : null}
                  </TD>
                  <TD className="tabular text-right">{p.subscriptions}</TD>
                  <TD className="text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setEditing(p);
                        setDialogOpen(true);
                      }}
                    >
                      {tc("edit")}
                    </Button>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
      <p className="text-xs text-fg-subtle">{t("plans.footnote")}</p>
      {dialogOpen ? <PlanDialog key={editing?.id ?? "new"} plan={editing} open={dialogOpen} onOpenChange={setDialogOpen} /> : null}
    </div>
  );
}
