"use client";

import { Alert, Badge, Button, Card, CardBody, CardFooter, CardHeader, ErrorState, PageHeader, SkeletonRows, toast } from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, Lock } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";

import { BILLING_KEY, type CheckoutResult, type SimulatedCheckout, errorText } from "@/components/billing";
import { http } from "@/lib/api";
import { formatDate, formatEur, formatNumber, localeTag } from "@/lib/format";
import { ME_KEY } from "@/lib/hooks/use-me";

export default function SimulatedCheckoutPage() {
  const t = useTranslations("billing");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const id = params.id;

  const checkout = useQuery({
    queryKey: [...BILLING_KEY, "checkout", id],
    queryFn: () => http.get<SimulatedCheckout>(`/billing/checkout/${id}`),
  });
  const finish = async (res: CheckoutResult) => {
    await Promise.all([qc.invalidateQueries({ queryKey: BILLING_KEY }), qc.invalidateQueries({ queryKey: ME_KEY })]);
    router.push(res.redirect);
  };
  const confirm = useMutation({
    mutationFn: () => http.post<CheckoutResult>(`/billing/checkout/${id}/confirm`),
    onSuccess: finish,
    onError: (err) => toast.error(errorText(err)),
  });
  const cancel = useMutation({
    mutationFn: () => http.post<CheckoutResult>(`/billing/checkout/${id}/cancel`),
    onSuccess: finish,
    onError: (err) => toast.error(errorText(err)),
  });

  if (checkout.isLoading) return <SkeletonRows rows={6} />;
  if (checkout.error || !checkout.data) {
    return (
      <ErrorState
        title={t("checkout.notFoundTitle")}
        description={errorText(checkout.error)}
        onRetry={() => void checkout.refetch()}
      />
    );
  }
  const data = checkout.data;
  const backHref = data.kind === "credit_pack" ? "/app/settings/credits" : "/app/settings/billing";
  const open = data.status === "open";

  return (
    <div className="mx-auto flex w-full max-w-xl flex-col gap-5">
      <PageHeader
        breadcrumbs={
          <Link href={backHref} className="hover:text-fg">
            ← {data.kind === "credit_pack" ? t("credits.title") : t("billing.title")}
          </Link>
        }
        title={t("checkout.title")}
        description={t("checkout.description", { org: data.org_name })}
      />
      <Alert tone="warning" title={t("checkout.testNotice")}>
        <span className="flex items-start gap-2">
          <FlaskConical className="mt-0.5 size-4 shrink-0" aria-hidden />
          {t("checkout.testExplanation")}
        </span>
      </Alert>
      <Card>
        <CardHeader
          title={t("checkout.summary")}
          actions={<Badge tone={open ? "info" : data.status === "completed" ? "success" : "neutral"}>{t(`checkout.status.${data.status}`)}</Badge>}
        />
        <CardBody className="flex flex-col gap-3 text-sm">
          {data.kind === "subscription" && data.plan ? (
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="font-medium">{t("checkout.planLine", { plan: data.plan.name })}</p>
                <p className="text-fg-muted">
                  {t(`interval.${data.interval ?? "month"}`)} ·{" "}
                  {t("checkout.planIncludes", {
                    credits: formatNumber(data.plan.limits.credits_month, locale),
                  })}
                </p>
              </div>
            </div>
          ) : null}
          {data.kind === "credit_pack" && data.pack ? (
            <p className="font-medium">{t("checkout.packLine", { credits: formatNumber(data.pack.credits, locale) })}</p>
          ) : null}
          <div className="flex items-baseline justify-between border-t border-border pt-3">
            <span className="text-fg-muted">{t("checkout.total")}</span>
            <span className="tabular text-lg font-semibold">
              {formatEur(data.amount_eur, locale, 2)}
              {data.kind === "subscription" && data.interval ? (
                <span className="text-sm font-normal text-fg-muted"> / {t(`intervalUnit.${data.interval}`)}</span>
              ) : null}
            </span>
          </div>
          <p className="text-xs text-fg-subtle">{t("checkout.vatNote")}</p>
          {open ? (
            <p className="text-xs text-fg-subtle">{t("checkout.expires", { date: formatDate(data.expires_at, locale, true) })}</p>
          ) : null}
        </CardBody>
        <CardFooter>
          {open ? (
            <>
              <Button variant="secondary" loading={cancel.isPending} disabled={confirm.isPending} onClick={() => cancel.mutate()}>
                {tc("cancel")}
              </Button>
              <Button variant="primary" loading={confirm.isPending} disabled={cancel.isPending} onClick={() => confirm.mutate()}>
                <Lock />
                {t("checkout.confirm", { amount: formatEur(data.amount_eur, locale, 2) })}
              </Button>
            </>
          ) : (
            <Button asChild variant="dark">
              <Link href={backHref}>{tc("back")}</Link>
            </Button>
          )}
        </CardFooter>
      </Card>
    </div>
  );
}
