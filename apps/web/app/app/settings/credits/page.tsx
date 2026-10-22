"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorState,
  Field,
  Input,
  PageHeader,
  Select,
  SkeletonRows,
  Stat,
  Switch,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  toast,
} from "@messer/ui";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Coins } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import {
  type CheckoutAction,
  CREDITS_KEY,
  type CreditsOverview,
  type LedgerKind,
  type LedgerPage,
  TestModeBadge,
  errorText,
  useFollowCheckout,
} from "@/components/billing";
import { http } from "@/lib/api";
import { formatDate, formatEur, formatNumber, formatUsd, localeTag } from "@/lib/format";
import { useRole } from "@/lib/hooks/use-me";

const PAGE_SIZE = 25;
const KIND_TONES = { grant: "info", purchase: "success", usage: "neutral", adjustment: "warning" } as const;

export default function CreditsSettingsPage() {
  return (
    <React.Suspense fallback={<SkeletonRows rows={8} />}>
      <CreditsSettings />
    </React.Suspense>
  );
}

function AutoTopupCard({ data, isOwner }: { data: CreditsOverview; isOwner: boolean }) {
  const t = useTranslations("billing");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const [enabled, setEnabled] = React.useState(data.auto_topup.enabled);
  const [threshold, setThreshold] = React.useState(String(data.auto_topup.threshold || 1000));
  const [packId, setPackId] = React.useState(data.auto_topup.pack_id ?? data.packs[0]?.id ?? "");
  const save = useMutation({
    mutationFn: () =>
      http.put<CreditsOverview>("/billing/credits/auto-topup", {
        enabled,
        threshold: Math.max(0, Math.round(Number(threshold) || 0)),
        pack_id: enabled ? packId : data.auto_topup.pack_id,
      }),
    onSuccess: (res) => {
      qc.setQueryData(CREDITS_KEY, res);
      toast.success(t("autoTopup.saved"));
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const last = data.auto_topup;
  return (
    <Card>
      <CardHeader title={t("autoTopup.title")} description={t("autoTopup.description")} />
      <CardBody className="flex flex-col gap-4">
        {!data.can_auto_topup ? <Alert tone="info">{t("autoTopup.needsPaymentMethod")}</Alert> : null}
        <label className="flex items-center gap-3 text-sm">
          <Switch
            checked={enabled}
            onCheckedChange={setEnabled}
            disabled={!isOwner || (!data.can_auto_topup && !enabled)}
            aria-label={t("autoTopup.enable")}
          />
          {t("autoTopup.enable")}
        </label>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("autoTopup.threshold")} htmlFor="topup-threshold" hint={t("autoTopup.thresholdHint")}>
            <Input
              id="topup-threshold"
              type="number"
              min={0}
              step={100}
              inputMode="numeric"
              value={threshold}
              disabled={!isOwner || !enabled}
              onChange={(e) => setThreshold(e.target.value)}
            />
          </Field>
          <Field label={t("autoTopup.pack")}>
            <Select
              value={packId}
              onValueChange={setPackId}
              disabled={!isOwner || !enabled}
              options={data.packs.map((p) => ({
                value: p.id,
                label: `${formatNumber(p.credits, locale)} ${t("credits.unit")} · ${formatEur(p.price_eur, locale, 2)}`,
              }))}
            />
          </Field>
        </div>
        {last.last_status ? (
          <p className="text-xs text-fg-muted">
            {t(`autoTopup.last.${last.last_status}`, {
              date: last.last_requested_at ? formatDate(last.last_requested_at, locale, true) : "—",
            })}
            {last.last_status === "failed" && last.last_error ? ` · ${last.last_error}` : ""}
          </p>
        ) : null}
        {isOwner ? (
          <div className="flex justify-end">
            <Button variant="dark" loading={save.isPending} onClick={() => save.mutate()}>
              {tc("save")}
            </Button>
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}

function CreditsSettings() {
  const t = useTranslations("billing");
  const ts = useTranslations("settings.sections");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const router = useRouter();
  const params = useSearchParams();
  const isOwner = useRole("owner");
  const follow = useFollowCheckout();
  const [kind, setKind] = React.useState<LedgerKind | "all">("all");
  const [page, setPage] = React.useState(0);

  const credits = useQuery({ queryKey: CREDITS_KEY, queryFn: () => http.get<CreditsOverview>("/billing/credits") });
  const ledger = useQuery({
    queryKey: [...CREDITS_KEY, "ledger", kind, page],
    queryFn: () =>
      http.get<LedgerPage>("/billing/credits/ledger", {
        kind: kind === "all" ? undefined : kind,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
    placeholderData: keepPreviousData,
  });

  const checkoutResult = params.get("checkout");
  React.useEffect(() => {
    if (!checkoutResult) return;
    if (checkoutResult === "success") toast.success(t("credits.purchased"));
    else if (checkoutResult === "canceled") toast(t("checkout.canceledToast"));
    void qc.invalidateQueries({ queryKey: CREDITS_KEY });
    router.replace("/app/settings/credits");
  }, [checkoutResult, qc, router, t]);

  const buy = useMutation({
    mutationFn: (packId: string) => http.post<CheckoutAction>("/billing/credits/purchase", { pack_id: packId }),
    onSuccess: (res) => {
      if (res.url) follow(res.url);
    },
    onError: (err) => toast.error(errorText(err)),
  });

  if (credits.isLoading) return <SkeletonRows rows={8} />;
  if (credits.error || !credits.data) {
    return <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void credits.refetch()} />;
  }
  const data = credits.data;
  const balance = Number(data.balance);
  const low = data.credits_month > 0 && balance < data.credits_month * 0.1;
  const creditUsd = Number(data.credit_usd);
  const totalPages = Math.max(1, Math.ceil((ledger.data?.total ?? 0) / PAGE_SIZE));

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            {ts("credits")}
            {data.test_mode ? <TestModeBadge /> : null}
          </span>
        }
        description={t("credits.description", { value: formatUsd(creditUsd, locale) })}
      />
      {balance <= 0 ? (
        <Alert tone="danger" title={t("credits.exhaustedTitle")}>
          {t("credits.exhausted")}
        </Alert>
      ) : low ? (
        <Alert tone="warning" title={t("credits.lowTitle")}>
          {t("credits.low")}
        </Alert>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label={t("credits.balance")}
          value={formatNumber(balance, locale)}
          hint={t("credits.balanceUsd", { value: formatUsd(balance * creditUsd, locale) })}
          tone={balance <= 0 ? "danger" : low ? "warning" : undefined}
        />
        <Stat label={t("credits.usedThisMonth")} value={formatNumber(data.used_this_month, locale)} />
        <Stat label={t("credits.addedThisMonth")} value={formatNumber(data.added_this_month, locale)} />
        <Stat
          label={t("credits.included")}
          value={data.credits_month === -1 ? t("usage.unlimited") : formatNumber(data.credits_month, locale)}
          hint={t("credits.perMonth")}
        />
      </div>

      <Card>
        <CardHeader title={t("credits.buyTitle")} description={t("credits.buyDescription")} />
        <CardBody className="grid gap-3 sm:grid-cols-3">
          {data.packs.map((pack) => (
            <div key={pack.id} className="flex flex-col gap-2 rounded-md border border-border p-4">
              <p className="tabular text-lg font-semibold">
                {formatNumber(pack.credits, locale)} <span className="text-sm font-normal text-fg-muted">{t("credits.unit")}</span>
              </p>
              <p className="tabular text-sm">
                {formatEur(pack.price_eur, locale, 2)}{" "}
                <span className="text-fg-subtle">
                  · {t("credits.per1k", { price: formatEur((Number(pack.price_eur) / pack.credits) * 1000, locale, 2) })}
                </span>
              </p>
              <Button
                variant="secondary"
                className="mt-auto"
                disabled={!isOwner || buy.isPending}
                loading={buy.isPending && buy.variables === pack.id}
                onClick={() => buy.mutate(pack.id)}
              >
                {t("credits.buy")}
              </Button>
            </div>
          ))}
          <p className="text-xs text-fg-subtle sm:col-span-3">{t("plans.vatExcluded")}</p>
        </CardBody>
      </Card>

      <AutoTopupCard key={JSON.stringify(data.auto_topup)} data={data} isOwner={isOwner} />

      <Card>
        <CardHeader
          title={t("ledger.title")}
          description={t("ledger.description")}
          actions={
            <Select
              aria-label={t("ledger.filter")}
              value={kind}
              onValueChange={(v) => {
                setKind(v as LedgerKind | "all");
                setPage(0);
              }}
              className="w-44"
              options={(["all", "grant", "purchase", "usage", "adjustment"] as const).map((k) => ({
                value: k,
                label: k === "all" ? tc("all") : t(`ledger.kinds.${k}`),
              }))}
            />
          }
        />
        {ledger.isLoading ? (
          <div className="p-4">
            <SkeletonRows rows={5} />
          </div>
        ) : ledger.error || !ledger.data ? (
          <div className="p-4">
            <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void ledger.refetch()} />
          </div>
        ) : ledger.data.items.length === 0 ? (
          <div className="p-4">
            <EmptyState icon={<Coins />} title={t("ledger.emptyTitle")} description={t("ledger.emptyDescription")} />
          </div>
        ) : (
          <>
            <Table>
              <THead>
                <tr>
                  <TH>{t("ledger.date")}</TH>
                  <TH>{t("ledger.kind")}</TH>
                  <TH>{t("ledger.detail")}</TH>
                  <TH className="text-right">{t("ledger.amount")}</TH>
                  <TH className="hidden text-right md:table-cell">{t("ledger.cost")}</TH>
                </tr>
              </THead>
              <TBody>
                {ledger.data.items.map((e) => {
                  const amount = Number(e.amount);
                  return (
                    <TR key={e.id}>
                      <TD className="whitespace-nowrap text-fg-muted">{formatDate(e.created_at, locale, true)}</TD>
                      <TD>
                        <Badge tone={KIND_TONES[e.kind]}>{t(`ledger.kinds.${e.kind}`)}</Badge>
                      </TD>
                      <TD className="max-w-md">
                        <span className="line-clamp-2">{e.note ?? "—"}</span>
                        {e.project_name ? <span className="block text-xs text-fg-subtle">{e.project_name}</span> : null}
                      </TD>
                      <TD className={`tabular text-right font-medium ${amount < 0 ? "text-fg" : "text-success"}`}>
                        {amount > 0 ? "+" : ""}
                        {formatNumber(amount, locale, 2)}
                      </TD>
                      <TD className="tabular hidden text-right text-fg-muted md:table-cell">
                        {e.cost_usd !== null ? formatUsd(e.cost_usd, locale) : "—"}
                      </TD>
                    </TR>
                  );
                })}
              </TBody>
            </Table>
            <div className="flex items-center justify-between border-t border-border px-4 py-2 text-sm text-fg-muted">
              <span>{t("ledger.pageOf", { page: page + 1, pages: totalPages, total: ledger.data.total })}</span>
              <div className="flex gap-2">
                <Button size="sm" disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>
                  {t("ledger.previous")}
                </Button>
                <Button size="sm" disabled={page + 1 >= totalPages} onClick={() => setPage((p) => p + 1)}>
                  {t("ledger.next")}
                </Button>
              </div>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
