"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  ConfirmDialog,
  Dialog,
  DialogContent,
  ErrorState,
  Field,
  Input,
  PageHeader,
  RadioCards,
  Select,
  SkeletonRows,
  Stat,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  Textarea,
  cn,
  toast,
} from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Coins, LogIn, Repeat, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { ImpersonateDialog, type ImpersonationTarget } from "@/components/admin/impersonate-dialog";
import { ADMIN_KEY, type AdminPlan, type OrgDetail, type OrgRow } from "@/components/admin/types";
import { STATE_TONES, UsageMeter, errorText } from "@/components/billing";
import { ApiError, http } from "@/lib/api";
import { formatDate, formatEur, formatNumber, formatRelative, formatUsd, localeTag } from "@/lib/format";

function CreditsDialog({ orgId, open, onOpenChange }: { orgId: string; open: boolean; onOpenChange: (o: boolean) => void }) {
  const t = useTranslations("admin");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const [mode, setMode] = React.useState<"grant" | "remove">("grant");
  const [amount, setAmount] = React.useState("");
  const [note, setNote] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (open) {
      setMode("grant");
      setAmount("");
      setNote("");
      setError(null);
    }
  }, [open]);
  const save = useMutation({
    mutationFn: () =>
      http.post<OrgRow>(`/admin/orgs/${orgId}/credits`, {
        amount: String(mode === "grant" ? Math.abs(Number(amount)) : -Math.abs(Number(amount))),
        note: note.trim(),
      }),
    onSuccess: () => {
      toast.success(t("detail.creditsSaved"));
      onOpenChange(false);
      void qc.invalidateQueries({ queryKey: ADMIN_KEY });
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });
  const valid = Number(amount) > 0 && note.trim().length >= 3;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={t("detail.creditsTitle")} description={t("detail.creditsDescription")}>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (valid) save.mutate();
          }}
        >
          {error ? <Alert tone="danger">{error}</Alert> : null}
          <RadioCards
            className="grid-cols-2"
            value={mode}
            onValueChange={(v) => setMode(v as "grant" | "remove")}
            options={[
              { value: "grant", label: t("detail.grant") },
              { value: "remove", label: t("detail.remove") },
            ]}
          />
          <Field label={t("detail.amount")} htmlFor="credits-amount">
            <Input
              id="credits-amount"
              type="number"
              min={1}
              step={1}
              required
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
          </Field>
          <Field label={t("detail.note")} htmlFor="credits-note" hint={t("detail.noteHint")}>
            <Textarea id="credits-note" required value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
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

function PlanDialog({
  detail,
  open,
  onOpenChange,
}: {
  detail: OrgDetail;
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const t = useTranslations("admin");
  const tb = useTranslations("billing");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const plans = useQuery({ queryKey: [...ADMIN_KEY, "plans"], queryFn: () => http.get<AdminPlan[]>("/admin/plans"), enabled: open });
  const [planId, setPlanId] = React.useState(detail.plan?.id ?? "pro");
  const [interval, setInterval] = React.useState<"month" | "year">(detail.subscription?.interval ?? "month");
  const [status, setStatus] = React.useState<"active" | "trialing">("active");
  const [trialDays, setTrialDays] = React.useState("14");
  const [note, setNote] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const save = useMutation({
    mutationFn: () =>
      http.post<OrgRow>(`/admin/orgs/${detail.org.id}/plan`, {
        plan_id: planId,
        interval,
        status,
        trial_days: Math.max(1, Math.min(90, Math.round(Number(trialDays) || 14))),
        note: note.trim() || null,
      }),
    onSuccess: () => {
      toast.success(t("detail.planSaved"));
      onOpenChange(false);
      void qc.invalidateQueries({ queryKey: ADMIN_KEY });
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });
  const providerManaged = Boolean(detail.subscription?.paid);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={t("detail.planTitle")} description={t("detail.planDescription")}>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          {error ? <Alert tone="danger">{error}</Alert> : null}
          {providerManaged ? <Alert tone="info">{t("detail.planProviderNote")}</Alert> : null}
          <Field label={t("detail.plan")}>
            <Select
              value={planId}
              onValueChange={setPlanId}
              options={(plans.data ?? []).map((p) => ({
                value: p.id,
                label: `${p.name}${p.public ? "" : ` · ${t("plans.private")}`}`,
              }))}
              placeholder={plans.isLoading ? tc("loading") : undefined}
            />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("detail.interval")}>
              <Select
                value={interval}
                onValueChange={(v) => setInterval(v as "month" | "year")}
                options={(["month", "year"] as const).map((v) => ({ value: v, label: tb(`interval.${v}`) }))}
              />
            </Field>
            <Field label={tc("status")}>
              <Select
                value={status}
                onValueChange={(v) => setStatus(v as "active" | "trialing")}
                options={[
                  { value: "active", label: t("detail.statusActive") },
                  { value: "trialing", label: t("detail.statusTrial") },
                ]}
              />
            </Field>
          </div>
          {status === "trialing" ? (
            <Field label={t("detail.trialDays")} htmlFor="trial-days">
              <Input id="trial-days" type="number" min={1} max={90} value={trialDays} onChange={(e) => setTrialDays(e.target.value)} />
            </Field>
          ) : null}
          <Field label={t("detail.note")} htmlFor="plan-note">
            <Textarea id="plan-note" value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
          <div className="mt-2 flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
              {tc("cancel")}
            </Button>
            <Button type="submit" variant="primary" loading={save.isPending} disabled={!planId}>
              {tc("save")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function AdminOrgDetailPage() {
  const t = useTranslations("admin");
  const tb = useTranslations("billing");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const { id } = useParams<{ id: string }>();
  const detail = useQuery({ queryKey: [...ADMIN_KEY, "org", id], queryFn: () => http.get<OrgDetail>(`/admin/orgs/${id}`) });
  const [creditsOpen, setCreditsOpen] = React.useState(false);
  const [planOpen, setPlanOpen] = React.useState(false);
  const [blockOpen, setBlockOpen] = React.useState(false);
  const [blockReason, setBlockReason] = React.useState("");
  const [impersonating, setImpersonating] = React.useState<ImpersonationTarget | null>(null);

  const block = useMutation({
    mutationFn: (blocked: boolean) =>
      blocked
        ? http.post<OrgRow>(`/admin/orgs/${id}/unblock`)
        : http.post<OrgRow>(`/admin/orgs/${id}/block`, { reason: blockReason.trim() }),
    onSuccess: () => {
      setBlockOpen(false);
      setBlockReason("");
      void qc.invalidateQueries({ queryKey: ADMIN_KEY });
    },
    onError: (err) => toast.error(errorText(err)),
  });

  if (detail.isLoading) return <SkeletonRows rows={10} />;
  if (detail.error || !detail.data) {
    return <ErrorState title={tc("errorTitle")} description={errorText(detail.error)} onRetry={() => void detail.refetch()} />;
  }
  const d = detail.data;
  const o = d.org;
  const sub = d.subscription;
  const blocked = o.status === "blocked";
  const fmtNum = (v: number) => formatNumber(v, locale);
  const margin = Number(o.margin_usd_month);
  const firstOwner = d.members.find((m) => m.role === "owner");

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        breadcrumbs={
          <Link href="/admin/orgs" className="hover:text-fg">
            ← {t("orgs.title")}
          </Link>
        }
        title={
          <span className="flex flex-wrap items-center gap-2">
            {o.name}
            {blocked ? <Badge tone="danger">{t("orgs.statusBlocked")}</Badge> : null}
            <Badge tone={STATE_TONES[o.subscription_status] ?? "neutral"}>{tb(`status.${o.subscription_status}`)}</Badge>
          </span>
        }
        description={t("detail.subtitle", { slug: o.slug, date: formatDate(o.created_at, locale), region: d.region })}
        actions={
          <>
            {firstOwner ? (
              <Button
                onClick={() =>
                  setImpersonating({ userId: firstOwner.user_id, email: firstOwner.email, orgs: [{ id: o.id, name: o.name }], orgId: o.id })
                }
                disabled={firstOwner.status === "blocked" || firstOwner.is_superadmin}
              >
                <LogIn />
                {t("detail.impersonateOwner")}
              </Button>
            ) : null}
            <Button onClick={() => setCreditsOpen(true)}>
              <Coins />
              {t("detail.adjustCredits")}
            </Button>
            <Button onClick={() => setPlanOpen(true)}>
              <Repeat />
              {t("detail.changePlan")}
            </Button>
            <Button variant={blocked ? "dark" : "danger"} onClick={() => setBlockOpen(true)}>
              {blocked ? <ShieldCheck /> : <Ban />}
              {blocked ? t("detail.unblock") : t("detail.block")}
            </Button>
          </>
        }
      />
      {blocked && o.blocked_reason ? (
        <Alert tone="danger" title={t("detail.blockedTitle")}>
          {o.blocked_reason}
        </Alert>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label={t("orgs.mrr")}
          value={Number(o.mrr_eur) > 0 ? formatEur(o.mrr_eur, locale, 2) : "—"}
          hint={o.plan_name ? `${o.plan_name}${sub ? ` · ${tb(`interval.${sub.interval}`)}` : ""}` : undefined}
        />
        <Stat label={t("detail.costMonth")} value={formatUsd(o.model_cost_usd_month, locale)} hint={t("detail.runsMonth", { count: o.runs_month })} />
        <Stat
          label={t("detail.marginMonth")}
          value={formatUsd(margin, locale)}
          hint={t("detail.revenueMonth", { value: formatUsd(o.credits_revenue_usd_month, locale) })}
          tone={margin < 0 ? "danger" : undefined}
        />
        <Stat
          label={t("orgs.balance")}
          value={formatNumber(o.credits_balance, locale)}
          hint={t("detail.creditsUsedMonth", { value: formatNumber(o.credits_used_month, locale) })}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title={t("detail.subscription")} />
          <CardBody>
            {sub ? (
              <dl className="grid grid-cols-[10rem_1fr] gap-x-3 gap-y-1.5 text-sm">
                <dt className="text-fg-muted">{t("detail.plan")}</dt>
                <dd>
                  {d.plan?.name ?? "—"} · {tb(`interval.${sub.interval}`)}
                  {sub.test_mode ? <Badge tone="warning" className="ml-2">{t("orgs.test")}</Badge> : null}
                </dd>
                <dt className="text-fg-muted">{tc("status")}</dt>
                <dd>
                  {tb(`status.${sub.state}`)}
                  {sub.cancel_at_period_end ? ` · ${t("detail.canceling")}` : ""}
                  {sub.read_only ? ` · ${t("detail.readOnly")}` : ""}
                </dd>
                {sub.trial_ends_at && (sub.state === "trialing" || sub.state === "trial_expired") ? (
                  <>
                    <dt className="text-fg-muted">{t("detail.trialEnds")}</dt>
                    <dd>{formatDate(sub.trial_ends_at, locale)}</dd>
                  </>
                ) : null}
                <dt className="text-fg-muted">{t("detail.period")}</dt>
                <dd>
                  {sub.current_period_start ? formatDate(sub.current_period_start, locale) : "—"} –{" "}
                  {sub.current_period_end ? formatDate(sub.current_period_end, locale) : "—"}
                </dd>
                {sub.past_due_since ? (
                  <>
                    <dt className="text-fg-muted">{t("detail.pastDueSince")}</dt>
                    <dd>
                      {formatDate(sub.past_due_since, locale)}
                      {sub.grace_ends_at ? ` · ${t("detail.graceEnds", { date: formatDate(sub.grace_ends_at, locale) })}` : ""}
                    </dd>
                  </>
                ) : null}
                <dt className="text-fg-muted">{t("detail.customer")}</dt>
                <dd className="truncate font-mono text-xs">{d.stripe_customer_id ?? "—"}</dd>
                <dt className="text-fg-muted">{t("detail.stripeSubscription")}</dt>
                <dd className="truncate font-mono text-xs">{d.stripe_subscription_id ?? t("detail.manual")}</dd>
              </dl>
            ) : (
              <p className="text-sm text-fg-subtle">{t("detail.noSubscription")}</p>
            )}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t("detail.usage")} />
          <CardBody className="grid gap-4 sm:grid-cols-2">
            <UsageMeter label={tb("limits.seats")} used={d.usage.seats.used} limit={d.usage.seats.limit} format={fmtNum} />
            <UsageMeter label={tb("limits.projects")} used={d.usage.projects.used} limit={d.usage.projects.limit} format={fmtNum} />
            <UsageMeter label={tb("limits.runs_month")} used={d.usage.runs_month.used} limit={d.usage.runs_month.limit} format={fmtNum} />
            <UsageMeter
              label={tb("usage.creditsUsed")}
              used={Number(d.usage.credits.used)}
              limit={d.usage.credits.limit}
              format={fmtNum}
            />
            <UsageMeter
              label={tb("limits.storage_gb")}
              used={d.usage.storage_gb.used}
              limit={d.usage.storage_gb.limit}
              format={(v) => `${formatNumber(v, locale, 2)} GB`}
            />
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader title={t("detail.members", { count: d.members.length })} />
        <Table>
          <THead>
            <tr>
              <TH>{tc("name")}</TH>
              <TH>{tc("role")}</TH>
              <TH className="hidden md:table-cell">{t("detail.lastLogin")}</TH>
              <TH className="w-32" />
            </tr>
          </THead>
          <TBody>
            {d.members.map((m) => (
              <TR key={m.user_id}>
                <TD>
                  <span className="font-medium">{m.name ?? m.email}</span>
                  {m.status === "blocked" ? <Badge tone="danger" className="ml-2">{t("users.blocked")}</Badge> : null}
                  {m.is_superadmin ? <Badge tone="accent" className="ml-2">{t("users.superadmin")}</Badge> : null}
                  <span className="block text-xs text-fg-subtle">{m.email}</span>
                </TD>
                <TD>{tc(`roles.${m.role}`)}</TD>
                <TD className="hidden text-fg-muted md:table-cell">
                  {m.last_login_at ? formatRelative(m.last_login_at, locale) : t("orgs.never")}
                </TD>
                <TD className="text-right">
                  {!m.is_superadmin && m.status !== "blocked" ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setImpersonating({ userId: m.user_id, email: m.email, orgs: [{ id: o.id, name: o.name }], orgId: o.id })}
                    >
                      <LogIn />
                      {t("users.impersonate")}
                    </Button>
                  ) : null}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader title={t("detail.projects", { count: d.projects.length })} />
          {d.projects.length === 0 ? (
            <p className="p-4 text-sm text-fg-subtle">{t("detail.noProjects")}</p>
          ) : (
            <Table>
              <THead>
                <tr>
                  <TH>{tc("name")}</TH>
                  <TH className="text-right">{t("detail.runs")}</TH>
                  <TH className="text-right">{t("detail.cost")}</TH>
                </tr>
              </THead>
              <TBody>
                {d.projects.map((p) => (
                  <TR key={p.id} className={cn(p.archived_at && "text-fg-subtle")}>
                    <TD>
                      {p.name}
                      <span className="block text-xs text-fg-subtle">
                        {formatDate(p.created_at, locale)}
                        {p.template_id ? ` · ${p.template_id}` : ""}
                        {p.archived_at ? ` · ${t("detail.archived")}` : ""}
                      </span>
                    </TD>
                    <TD className="tabular text-right">{formatNumber(p.runs_month, locale)}</TD>
                    <TD className="tabular text-right">{formatUsd(p.cost_usd_month, locale)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </Card>
        <Card>
          <CardHeader title={t("detail.ledger")} />
          {d.ledger.length === 0 ? (
            <p className="p-4 text-sm text-fg-subtle">{t("detail.noLedger")}</p>
          ) : (
            <Table>
              <THead>
                <tr>
                  <TH>{t("detail.date")}</TH>
                  <TH>{t("detail.kind")}</TH>
                  <TH className="text-right">{t("detail.amount")}</TH>
                </tr>
              </THead>
              <TBody>
                {d.ledger.map((e) => (
                  <TR key={e.id}>
                    <TD className="whitespace-nowrap text-fg-muted">{formatDate(e.created_at, locale, true)}</TD>
                    <TD>
                      {tb(`ledger.kinds.${e.kind}`)}
                      <span className="block max-w-xs truncate text-xs text-fg-subtle">
                        {e.note ?? ""}
                        {e.created_by_email ? ` · ${e.created_by_email}` : ""}
                      </span>
                    </TD>
                    <TD className={cn("tabular text-right", Number(e.amount) > 0 && "text-success")}>
                      {Number(e.amount) > 0 ? "+" : ""}
                      {formatNumber(e.amount, locale, 2)}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader title={t("detail.invoices")} />
          {d.invoices.length === 0 ? (
            <p className="p-4 text-sm text-fg-subtle">{t("detail.noInvoices")}</p>
          ) : (
            <Table>
              <THead>
                <tr>
                  <TH>{t("detail.date")}</TH>
                  <TH>{tc("status")}</TH>
                  <TH className="text-right">{t("detail.amount")}</TH>
                </tr>
              </THead>
              <TBody>
                {d.invoices.map((i) => (
                  <TR key={i.id}>
                    <TD className="text-fg-muted">
                      {formatDate(i.created_at, locale)}
                      <span className="block font-mono text-xs">{i.number ?? i.stripe_invoice_id}</span>
                    </TD>
                    <TD>
                      {tb.has(`invoiceStatus.${i.status}`) ? tb(`invoiceStatus.${i.status}`) : i.status}
                      {i.test ? <Badge tone="warning" className="ml-2">{t("orgs.test")}</Badge> : null}
                    </TD>
                    <TD className="tabular text-right">{formatEur(i.amount_paid_eur, locale, 2)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </Card>
        <Card>
          <CardHeader title={t("detail.audit")} />
          {d.audit.length === 0 ? (
            <p className="p-4 text-sm text-fg-subtle">{t("detail.noAudit")}</p>
          ) : (
            <ul className="max-h-96 divide-y divide-border overflow-y-auto text-sm">
              {d.audit.map((a) => (
                <li key={a.id} className="px-4 py-2">
                  <p className="flex items-center justify-between gap-2">
                    <span className="font-mono text-xs">{a.action}</span>
                    <span className="text-xs text-fg-subtle">{formatDate(a.created_at, locale, true)}</span>
                  </p>
                  <p className="text-xs text-fg-muted">
                    {a.actor_email ?? t("audit.system")}
                    {a.impersonated_by_email ? ` · ${t("audit.via", { email: a.impersonated_by_email })}` : ""}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <CreditsDialog orgId={o.id} open={creditsOpen} onOpenChange={setCreditsOpen} />
      <PlanDialog key={planOpen ? "open" : "closed"} detail={d} open={planOpen} onOpenChange={setPlanOpen} />
      <ImpersonateDialog target={impersonating} onClose={() => setImpersonating(null)} />
      <ConfirmDialog
        open={blockOpen}
        onOpenChange={setBlockOpen}
        title={blocked ? t("detail.unblockTitle", { org: o.name }) : t("detail.blockTitle", { org: o.name })}
        description={blocked ? t("detail.unblockDescription") : t("detail.blockDescription")}
        confirmLabel={blocked ? t("detail.unblock") : t("detail.block")}
        cancelLabel={tc("cancel")}
        destructive={!blocked}
        loading={block.isPending}
        onConfirm={() => {
          if (blocked || blockReason.trim().length >= 3) block.mutate(blocked);
          else toast.error(t("detail.reasonRequired"));
        }}
      >
        {!blocked ? (
          <Field label={t("detail.reason")} htmlFor="block-reason">
            <Textarea id="block-reason" value={blockReason} onChange={(e) => setBlockReason(e.target.value)} />
          </Field>
        ) : null}
      </ConfirmDialog>
    </div>
  );
}
