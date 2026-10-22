"use client";

import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Input,
  PageHeader,
  Select,
  SkeletonRows,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  cn,
} from "@messer/ui";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Building2, Search } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { ADMIN_KEY, type OrgPage } from "@/components/admin/types";
import { PLANS_KEY, type Plan, STATE_TONES } from "@/components/billing";
import { http } from "@/lib/api";
import { formatEur, formatNumber, formatRelative, formatUsd, localeTag } from "@/lib/format";

const PAGE_SIZE = 50;
const PAYMENT_STATUSES = ["trialing", "active", "past_due", "canceled", "incomplete", "none"] as const;

function useDebounced<T>(value: T, ms = 300): T {
  const [debounced, setDebounced] = React.useState(value);
  React.useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), ms);
    return () => window.clearTimeout(id);
  }, [value, ms]);
  return debounced;
}

export default function AdminOrgsPage() {
  const t = useTranslations("admin");
  const tb = useTranslations("billing");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const [q, setQ] = React.useState("");
  const [paymentStatus, setPaymentStatus] = React.useState("all");
  const [planId, setPlanId] = React.useState("all");
  const [status, setStatus] = React.useState("all");
  const [sort, setSort] = React.useState("created");
  const [page, setPage] = React.useState(0);
  const search = useDebounced(q);
  React.useEffect(() => setPage(0), [search, paymentStatus, planId, status, sort]);

  const plans = useQuery({ queryKey: PLANS_KEY, queryFn: () => http.get<Plan[]>("/plans"), staleTime: 300_000 });
  const orgs = useQuery({
    queryKey: [...ADMIN_KEY, "orgs", search, paymentStatus, planId, status, sort, page],
    queryFn: () =>
      http.get<OrgPage>("/admin/orgs", {
        q: search || undefined,
        payment_status: paymentStatus === "all" ? undefined : paymentStatus,
        plan_id: planId === "all" ? undefined : planId,
        status: status === "all" ? undefined : status,
        sort,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
    placeholderData: keepPreviousData,
  });
  const total = orgs.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="flex flex-col gap-4">
      <PageHeader title={t("orgs.title")} description={t("orgs.description")} />
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full max-w-xs">
          <Search className="pointer-events-none absolute left-2.5 top-2 size-4 text-fg-subtle" aria-hidden />
          <Input
            className="pl-8"
            placeholder={t("orgs.search")}
            aria-label={t("orgs.search")}
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <Select
          className="w-44"
          aria-label={t("orgs.paymentStatus")}
          value={paymentStatus}
          onValueChange={setPaymentStatus}
          options={[
            { value: "all", label: t("orgs.allPayments") },
            ...PAYMENT_STATUSES.map((s) => ({ value: s, label: tb(`status.${s}`) })),
          ]}
        />
        <Select
          className="w-44"
          aria-label={t("orgs.plan")}
          value={planId}
          onValueChange={setPlanId}
          options={[{ value: "all", label: t("orgs.allPlans") }, ...(plans.data ?? []).map((p) => ({ value: p.id, label: p.name }))]}
        />
        <Select
          className="w-44"
          aria-label={tc("status")}
          value={status}
          onValueChange={setStatus}
          options={[
            { value: "all", label: t("orgs.allStatuses") },
            { value: "active", label: t("orgs.statusActive") },
            { value: "blocked", label: t("orgs.statusBlocked") },
          ]}
        />
        <Select
          className="ml-auto w-48"
          aria-label={t("orgs.sort")}
          value={sort}
          onValueChange={setSort}
          options={(["created", "name", "cost", "last_active"] as const).map((s) => ({ value: s, label: t(`orgs.sorts.${s}`) }))}
        />
      </div>
      <Card>
        {orgs.isLoading ? (
          <div className="p-4">
            <SkeletonRows rows={8} />
          </div>
        ) : orgs.error || !orgs.data ? (
          <div className="p-4">
            <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void orgs.refetch()} />
          </div>
        ) : orgs.data.items.length === 0 ? (
          <div className="p-4">
            <EmptyState icon={<Building2 />} title={t("orgs.emptyTitle")} description={t("orgs.empty")} />
          </div>
        ) : (
          <>
            <Table className={cn(orgs.isFetching && "opacity-70")}>
              <THead>
                <tr>
                  <TH>{t("orgs.org")}</TH>
                  <TH>{t("orgs.plan")}</TH>
                  <TH className="text-right">{t("orgs.mrr")}</TH>
                  <TH className="hidden text-right lg:table-cell">{t("orgs.usage")}</TH>
                  <TH className="hidden text-right md:table-cell">{t("orgs.cost")}</TH>
                  <TH className="hidden text-right md:table-cell">{t("orgs.margin")}</TH>
                  <TH className="hidden text-right xl:table-cell">{t("orgs.balance")}</TH>
                  <TH className="hidden lg:table-cell">{t("orgs.lastActive")}</TH>
                </tr>
              </THead>
              <TBody>
                {orgs.data.items.map((o) => {
                  const margin = Number(o.margin_usd_month);
                  return (
                    <TR key={o.id}>
                      <TD>
                        <Link href={`/admin/orgs/${o.id}`} className="font-medium hover:underline">
                          {o.name}
                        </Link>
                        {o.status === "blocked" ? (
                          <Badge tone="danger" className="ml-2">
                            {t("orgs.statusBlocked")}
                          </Badge>
                        ) : null}
                        <span className="block text-xs text-fg-subtle">{o.owner_email ?? o.slug}</span>
                      </TD>
                      <TD>
                        <span className="flex flex-wrap items-center gap-1.5">
                          {o.plan_name ?? "—"}
                          <Badge tone={STATE_TONES[o.subscription_status] ?? "neutral"}>{tb(`status.${o.subscription_status}`)}</Badge>
                          {o.test_mode && o.subscription_status !== "trialing" ? <Badge tone="warning">{t("orgs.test")}</Badge> : null}
                        </span>
                      </TD>
                      <TD className="tabular text-right">{Number(o.mrr_eur) > 0 ? formatEur(o.mrr_eur, locale, 2) : "—"}</TD>
                      <TD className="tabular hidden text-right text-fg-muted lg:table-cell">
                        {t("orgs.usageCell", { members: o.members, projects: o.projects, runs: o.runs_month })}
                      </TD>
                      <TD className="tabular hidden text-right md:table-cell">{formatUsd(o.model_cost_usd_month, locale)}</TD>
                      <TD className={cn("tabular hidden text-right md:table-cell", margin < 0 && "text-danger")}>
                        {formatUsd(margin, locale)}
                      </TD>
                      <TD className="tabular hidden text-right xl:table-cell">{formatNumber(o.credits_balance, locale)}</TD>
                      <TD className="hidden text-fg-muted lg:table-cell">
                        {o.last_active_at ? formatRelative(o.last_active_at, locale) : t("orgs.never")}
                      </TD>
                    </TR>
                  );
                })}
              </TBody>
            </Table>
            <div className="flex items-center justify-between border-t border-border px-4 py-2 text-sm text-fg-muted">
              <span>{t("orgs.pageOf", { page: page + 1, pages, total })}</span>
              <div className="flex gap-2">
                <Button size="sm" disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>
                  {t("common.previous")}
                </Button>
                <Button size="sm" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}>
                  {t("common.next")}
                </Button>
              </div>
            </div>
          </>
        )}
      </Card>
      <p className="text-xs text-fg-subtle">{t("orgs.footnote")}</p>
    </div>
  );
}
