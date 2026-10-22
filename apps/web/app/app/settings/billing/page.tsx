"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  PageHeader,
  SkeletonRows,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  Tooltip,
  toast,
} from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, FileText, Receipt } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import {
  BILLING_KEY,
  type BillingOverview,
  type CheckoutAction,
  type Interval,
  type Invoice,
  IntervalToggle,
  type Plan,
  type PlanAction,
  PlanGrid,
  PLANS_KEY,
  STATE_TONES,
  TestModeBadge,
  UsageMeter,
  errorText,
  formatUtcDate,
  inclusiveEnd,
  useFollowCheckout,
} from "@/components/billing";
import { http } from "@/lib/api";
import { formatDate, formatEur, formatNumber, localeTag } from "@/lib/format";
import { ME_KEY, useRole } from "@/lib/hooks/use-me";

export default function BillingSettingsPage() {
  return (
    <React.Suspense fallback={<SkeletonRows rows={8} />}>
      <BillingSettings />
    </React.Suspense>
  );
}

function BillingSettings() {
  const t = useTranslations("billing");
  const ts = useTranslations("settings.sections");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const router = useRouter();
  const params = useSearchParams();
  const isOwner = useRole("owner");
  const follow = useFollowCheckout();

  const overview = useQuery({ queryKey: BILLING_KEY, queryFn: () => http.get<BillingOverview>("/billing") });
  const plans = useQuery({ queryKey: PLANS_KEY, queryFn: () => http.get<Plan[]>("/plans"), staleTime: 300_000 });
  const invoices = useQuery({
    queryKey: [...BILLING_KEY, "invoices"],
    queryFn: () => http.get<Invoice[]>("/billing/invoices"),
    enabled: isOwner,
  });

  const sub = overview.data?.subscription ?? null;
  const [interval, setInterval] = React.useState<Interval>("month");
  const intervalTouched = React.useRef(false);
  React.useEffect(() => {
    if (sub && !intervalTouched.current) setInterval(sub.interval);
  }, [sub]);
  const [pending, setPending] = React.useState<{ plan: Plan; interval: Interval } | null>(null);
  const [cancelOpen, setCancelOpen] = React.useState(false);
  const highlight = params.get("plan");

  const refresh = React.useCallback(async () => {
    await Promise.all([qc.invalidateQueries({ queryKey: BILLING_KEY }), qc.invalidateQueries({ queryKey: ME_KEY })]);
  }, [qc]);

  const checkoutResult = params.get("checkout");
  React.useEffect(() => {
    if (!checkoutResult) return;
    if (checkoutResult === "success") toast.success(t("checkout.successToast"));
    else if (checkoutResult === "canceled") toast(t("checkout.canceledToast"));
    void refresh();
    router.replace("/app/settings/billing");
  }, [checkoutResult, refresh, router, t]);

  React.useEffect(() => {
    if (highlight && plans.data) document.getElementById(`plan-${highlight}`)?.scrollIntoView({ block: "center" });
  }, [highlight, plans.data]);

  const change = useMutation({
    mutationFn: (body: { plan_id: string; interval: Interval }) => http.post<CheckoutAction>("/billing/subscription", body),
    onSuccess: async (res) => {
      if (res.action === "checkout" && res.url) {
        follow(res.url);
        return;
      }
      setPending(null);
      toast.success(t("plans.changed"));
      await refresh();
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const setOverview = (data: BillingOverview) => {
    qc.setQueryData(BILLING_KEY, data);
    void qc.invalidateQueries({ queryKey: ME_KEY });
  };
  const cancel = useMutation({
    mutationFn: () => http.post<BillingOverview>("/billing/subscription/cancel"),
    onSuccess: (data) => {
      setCancelOpen(false);
      setOverview(data);
      toast.success(t("current.cancelScheduled"));
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const resume = useMutation({
    mutationFn: () => http.post<BillingOverview>("/billing/subscription/resume"),
    onSuccess: (data) => {
      setOverview(data);
      toast.success(t("current.resumed"));
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const portal = useMutation({
    mutationFn: () => http.post<{ url: string }>("/billing/portal"),
    onSuccess: (res) => window.location.assign(res.url),
    onError: (err) => toast.error(errorText(err)),
  });
  const simulate = useMutation({
    mutationFn: (outcome: "payment_failed" | "payment_succeeded") =>
      http.post<BillingOverview>(`/billing/simulate/${outcome}`),
    onSuccess: (data) => setOverview(data),
    onError: (err) => toast.error(errorText(err)),
  });

  if (overview.isLoading) return <SkeletonRows rows={8} />;
  if (overview.error || !overview.data) {
    return <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void overview.refetch()} />;
  }
  const data = overview.data;
  const plan = data.plan;
  const paid = Boolean(sub?.paid);
  const simulated = data.mode === "simulated";
  const state = sub?.state ?? "none";
  const usage = data.usage;
  const fmtNum = (v: number) => formatNumber(v, locale);
  const fmtDate = (v: string | null) => (v ? formatDate(v, locale) : "—");

  const actionFor = (p: Plan): PlanAction => {
    if (!p.self_serve) return { label: t("plans.contactSales"), href: `/contact?plan=${p.id}`, variant: "secondary" };
    const isCurrent = paid && plan?.id === p.id && sub?.interval === interval;
    if (isCurrent) {
      return sub?.cancel_at_period_end
        ? { label: t("current.resume"), onClick: () => resume.mutate(), disabled: !isOwner, loading: resume.isPending, variant: "dark" }
        : { label: t("plans.currentPlan"), disabled: true };
    }
    const loading = change.isPending && change.variables?.plan_id === p.id;
    if (!paid) {
      return {
        label: t("plans.subscribe", { plan: p.name }),
        onClick: () => change.mutate({ plan_id: p.id, interval }),
        disabled: !isOwner || change.isPending,
        loading,
        variant: highlight === p.id || p.id === plan?.id ? "primary" : "secondary",
      };
    }
    const upgrade = plan ? Number(p.price_month_eur) > Number(plan.price_month_eur) : true;
    return {
      label: plan?.id === p.id ? t("plans.switchInterval") : upgrade ? t("plans.upgrade") : t("plans.downgrade"),
      onClick: () => setPending({ plan: p, interval }),
      disabled: !isOwner || change.isPending,
      loading,
      variant: upgrade ? "primary" : "secondary",
    };
  };

  const priceLine = () => {
    if (!plan) return null;
    if (state === "trialing" && sub?.trial_ends_at) {
      const days = Math.max(0, Math.ceil((new Date(sub.trial_ends_at).getTime() - Date.now()) / 86_400_000));
      return t("current.trialUntil", { date: fmtDate(sub.trial_ends_at), days });
    }
    if (!sub) return null;
    const amount = sub.interval === "year" ? plan.price_year_eur : plan.price_month_eur;
    return t("current.price", { amount: formatEur(amount, locale, 2), interval: t(`intervalUnit.${sub.interval}`) });
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            {ts("billing")}
            {data.test_mode ? <TestModeBadge /> : null}
          </span>
        }
        description={t("billing.description")}
        actions={
          isOwner && sub?.has_customer ? (
            simulated ? (
              <Tooltip content={t("billing.portalUnavailable")}>
                <span tabIndex={0}>
                  <Button disabled>
                    <ExternalLink />
                    {t("billing.portal")}
                  </Button>
                </span>
              </Tooltip>
            ) : (
              <Button onClick={() => portal.mutate()} loading={portal.isPending}>
                <ExternalLink />
                {t("billing.portal")}
              </Button>
            )
          ) : null
        }
      />

      {simulated ? <Alert tone="warning" title={t("testMode.title")}>{t("testMode.banner")}</Alert> : null}
      {state === "past_due" ? (
        <Alert tone="warning" title={t("alerts.pastDueTitle")}>
          {t("alerts.pastDue", { date: fmtDate(sub?.grace_ends_at ?? null) })}
        </Alert>
      ) : null}
      {sub?.read_only ? (
        <Alert tone="danger" title={t("alerts.readOnlyTitle")}>
          {state === "trial_expired" ? t("alerts.trialExpired") : t("alerts.readOnly")}
        </Alert>
      ) : null}
      {sub?.cancel_at_period_end && sub.status !== "canceled" ? (
        <Alert
          tone="info"
          title={t("alerts.cancelingTitle")}
          action={
            isOwner ? (
              <Button size="sm" variant="dark" loading={resume.isPending} onClick={() => resume.mutate()}>
                {t("current.resume")}
              </Button>
            ) : null
          }
        >
          {t("alerts.canceling", { date: fmtDate(sub.current_period_end) })}
        </Alert>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-2">
          <CardHeader title={t("current.title")} />
          <CardBody className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-lg font-semibold">{plan?.name ?? t("current.noPlan")}</span>
              <Badge tone={STATE_TONES[state] ?? "neutral"}>{t(`status.${state}`)}</Badge>
              {sub && paid ? <Badge tone="outline">{t(`interval.${sub.interval}`)}</Badge> : null}
            </div>
            {priceLine() ? <p className="tabular text-sm text-fg-muted">{priceLine()}</p> : null}
            {paid && sub?.current_period_end && !sub.cancel_at_period_end ? (
              <p className="text-sm text-fg-muted">{t("current.renews", { date: fmtDate(sub.current_period_end) })}</p>
            ) : null}
            {!paid && plan ? <p className="text-sm text-fg-muted">{t("current.choosePlanHint")}</p> : null}
            {isOwner && paid ? (
              <div className="flex flex-wrap gap-2 pt-1">
                {!sub?.cancel_at_period_end ? (
                  <Button variant="danger" size="sm" onClick={() => setCancelOpen(true)}>
                    {t("current.cancel")}
                  </Button>
                ) : null}
                {simulated ? (
                  state === "past_due" ? (
                    <Button size="sm" loading={simulate.isPending} onClick={() => simulate.mutate("payment_succeeded")}>
                      {t("testMode.simulateSuccess")}
                    </Button>
                  ) : (
                    <Button size="sm" loading={simulate.isPending} onClick={() => simulate.mutate("payment_failed")}>
                      {t("testMode.simulateFailure")}
                    </Button>
                  )
                ) : null}
              </div>
            ) : null}
            {!isOwner ? <p className="text-xs text-fg-subtle">{t("billing.ownerOnly")}</p> : null}
          </CardBody>
        </Card>

        <Card className="lg:col-span-3">
          <CardHeader
            title={t("usage.title")}
            description={t("usage.period", {
              start: formatUtcDate(usage.period_start, locale),
              end: formatUtcDate(inclusiveEnd(usage.period_end), locale),
            })}
          />
          <CardBody className="grid gap-4 sm:grid-cols-2">
            <UsageMeter label={t("limits.seats")} used={usage.seats.used} limit={usage.seats.limit} format={fmtNum} />
            <UsageMeter label={t("limits.projects")} used={usage.projects.used} limit={usage.projects.limit} format={fmtNum} />
            <UsageMeter
              label={t("limits.runs_month")}
              used={usage.runs_month.used}
              limit={usage.runs_month.limit}
              format={fmtNum}
            />
            <UsageMeter
              label={t("usage.creditsUsed")}
              used={Number(usage.credits.used)}
              limit={usage.credits.limit}
              format={fmtNum}
            />
            <UsageMeter
              label={t("limits.storage_gb")}
              used={usage.storage_gb.used}
              limit={usage.storage_gb.limit}
              format={(v) => `${formatNumber(v, locale, 2)} GB`}
            />
            <div className="flex flex-col justify-end text-sm">
              <span className="text-fg-muted">{t("usage.balance")}</span>
              <span className="tabular text-lg font-semibold">{formatNumber(usage.credits.balance, locale)}</span>
            </div>
          </CardBody>
        </Card>
      </div>

      <section id="plans" className="flex flex-col gap-3 scroll-mt-16">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-md font-semibold">{t("plans.title")}</h2>
            <p className="text-sm text-fg-muted">{t("plans.description")}</p>
          </div>
          {plans.data ? (
            <IntervalToggle
              value={interval}
              plans={plans.data}
              onChange={(v) => {
                intervalTouched.current = true;
                setInterval(v);
              }}
            />
          ) : null}
        </div>
        {plans.isLoading ? (
          <SkeletonRows rows={4} />
        ) : plans.error || !plans.data ? (
          <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void plans.refetch()} />
        ) : (
          <PlanGrid
            plans={plans.data}
            interval={interval}
            currentPlanId={plan?.id ?? null}
            highlightId={highlight}
            actionFor={actionFor}
          />
        )}
      </section>

      {isOwner ? (
        <Card>
          <CardHeader title={t("invoices.title")} description={t("invoices.description")} />
          {invoices.isLoading ? (
            <div className="p-4">
              <SkeletonRows rows={3} />
            </div>
          ) : invoices.error ? (
            <div className="p-4">
              <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void invoices.refetch()} />
            </div>
          ) : (invoices.data ?? []).length === 0 ? (
            <div className="p-4">
              <EmptyState icon={<Receipt />} title={t("invoices.emptyTitle")} description={t("invoices.emptyDescription")} />
            </div>
          ) : (
            <Table>
              <THead>
                <tr>
                  <TH>{t("invoices.number")}</TH>
                  <TH>{t("invoices.date")}</TH>
                  <TH className="hidden md:table-cell">{t("invoices.period")}</TH>
                  <TH className="text-right">{t("invoices.amount")}</TH>
                  <TH className="hidden text-right sm:table-cell">{t("invoices.tax")}</TH>
                  <TH>{tc("status")}</TH>
                  <TH className="w-20" />
                </tr>
              </THead>
              <TBody>
                {(invoices.data ?? []).map((inv) => (
                  <TR key={inv.id}>
                    <TD>
                      <span className="font-mono text-xs">{inv.number ?? inv.stripe_invoice_id}</span>
                      {inv.test ? (
                        <Badge tone="warning" className="ml-2">
                          {t("testMode.badge")}
                        </Badge>
                      ) : null}
                    </TD>
                    <TD className="text-fg-muted">{formatDate(inv.created_at, locale)}</TD>
                    <TD className="hidden text-fg-muted md:table-cell">
                      {inv.period_start && inv.period_end && inv.period_start !== inv.period_end
                        ? `${formatDate(inv.period_start, locale)} – ${formatDate(inv.period_end, locale)}`
                        : "—"}
                    </TD>
                    <TD className="tabular text-right">{formatEur(inv.amount_due_eur, locale, 2)}</TD>
                    <TD className="tabular hidden text-right text-fg-muted sm:table-cell">{formatEur(inv.tax_eur, locale, 2)}</TD>
                    <TD>
                      <Badge tone={inv.status === "paid" ? "success" : inv.status === "open" ? "warning" : "neutral"}>
                        {t.has(`invoiceStatus.${inv.status}`) ? t(`invoiceStatus.${inv.status}`) : inv.status}
                      </Badge>
                    </TD>
                    <TD className="text-right">
                      {inv.pdf_url || inv.hosted_invoice_url ? (
                        <Button asChild variant="ghost" size="sm">
                          <a href={inv.pdf_url ?? inv.hosted_invoice_url ?? "#"} target="_blank" rel="noreferrer noopener">
                            <FileText />
                            {t("invoices.download")}
                          </a>
                        </Button>
                      ) : (
                        <span className="text-xs text-fg-subtle">{t("invoices.noPdf")}</span>
                      )}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </Card>
      ) : null}

      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(open) => !open && setPending(null)}
        title={t("plans.confirmTitle", { plan: pending?.plan.name ?? "" })}
        description={
          pending
            ? t("plans.confirmDescription", {
                amount: formatEur(pending.interval === "year" ? pending.plan.price_year_eur : pending.plan.price_month_eur, locale, 2),
                interval: t(`intervalUnit.${pending.interval}`),
              })
            : undefined
        }
        confirmLabel={t("plans.confirm")}
        cancelLabel={tc("cancel")}
        destructive={false}
        loading={change.isPending}
        onConfirm={() => {
          if (pending) change.mutate({ plan_id: pending.plan.id, interval: pending.interval });
        }}
      />
      <ConfirmDialog
        open={cancelOpen}
        onOpenChange={setCancelOpen}
        title={t("current.cancelTitle")}
        description={t("current.cancelDescription", { date: fmtDate(sub?.current_period_end ?? null) })}
        confirmLabel={t("current.cancelConfirm")}
        cancelLabel={t("current.keep")}
        loading={cancel.isPending}
        onConfirm={() => cancel.mutate()}
      />
    </div>
  );
}
