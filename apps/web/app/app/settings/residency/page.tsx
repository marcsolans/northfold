"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  ConfirmDialog,
  ErrorState,
  Field,
  Input,
  PageHeader,
  RadioCards,
  Select,
  Skeleton,
  StatusDot,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  toast,
} from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { PlanLimitNotice, billingHref } from "@/components/billing";
import type { ResidencyOverview, SystemStatus } from "@/components/enterprise/types";
import { ApiError, http } from "@/lib/api";
import { formatDate, formatNumber, localeTag } from "@/lib/format";
import { useInvalidateMe, useRole } from "@/lib/hooks/use-me";

type Mode = ResidencyOverview["data_residency"];

export default function ResidencyPage() {
  const t = useTranslations("enterprise.residency");
  const te = useTranslations("enterprise");
  const ts = useTranslations("settings.sections");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const invalidateMe = useInvalidateMe();
  const isAdmin = useRole("admin");

  const overview = useQuery({ queryKey: ["residency"], queryFn: () => http.get<ResidencyOverview>("/residency") });
  const status = useQuery({ queryKey: ["system-status"], queryFn: () => http.get<SystemStatus>("/system/status") });

  const [mode, setMode] = React.useState<Mode>("standard");
  const [region, setRegion] = React.useState("eu-central-1");
  const [traceDays, setTraceDays] = React.useState("90");
  const [conversationDays, setConversationDays] = React.useState("365");
  const [confirmStrict, setConfirmStrict] = React.useState(false);

  const data = overview.data;
  React.useEffect(() => {
    if (!data) return;
    setMode(data.data_residency);
    setRegion(data.region);
    setTraceDays(String(data.retention.trace_days));
    setConversationDays(String(data.retention.conversation_days));
  }, [data]);

  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, string | number> = {};
      if (data && mode !== data.data_residency) body.data_residency = mode;
      if (data && region !== data.region) body.region = region;
      if (data && traceDays !== String(data.retention.trace_days)) body.trace_retention_days = Number(traceDays);
      if (data && conversationDays !== String(data.retention.conversation_days)) {
        body.conversation_retention_days = Number(conversationDays);
      }
      return http.patch("/orgs/current", body);
    },
    onSuccess: async () => {
      setConfirmStrict(false);
      toast.success(t("saved"));
      await Promise.all([qc.invalidateQueries({ queryKey: ["residency"] }), invalidateMe()]);
    },
    onError: (err) => {
      setConfirmStrict(false);
      if (!(err instanceof ApiError && err.status === 402)) toast.error(err instanceof ApiError ? err.message : String(err));
    },
  });

  const validDays = (v: string) => /^\d+$/.test(v) && Number(v) >= 1 && Number(v) <= 3650;
  const dirty =
    data !== undefined &&
    (mode !== data.data_residency ||
      region !== data.region ||
      traceDays !== String(data.retention.trace_days) ||
      conversationDays !== String(data.retention.conversation_days));
  const canSave = isAdmin && dirty && validDays(traceDays) && validDays(conversationDays);

  const submit = () => {
    if (mode === "eu_strict" && data?.data_residency !== "eu_strict") setConfirmStrict(true);
    else save.mutate();
  };

  if (overview.isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }
  if (overview.error || !data) {
    return <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void overview.refetch()} />;
  }

  const bedrockReady = status.data?.bedrock_available ?? data.bedrock.configured;
  const lastPurge = data.retention.last_purge as { runs?: number; conversations?: number } | null;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={ts("residency")} description={t("description")} />
      {!isAdmin ? <Alert tone="info">{t("readOnly")}</Alert> : null}
      <PlanLimitNotice error={save.error} />

      <Card>
        <CardHeader title={t("mode")} />
        <CardBody className="flex flex-col gap-4">
          <RadioCards
            className="sm:grid-cols-2"
            value={mode}
            onValueChange={(v) => setMode(v as Mode)}
            options={[
              { value: "standard", label: t("standard"), description: t("standardDescription"), disabled: !isAdmin },
              {
                value: "eu_strict",
                label: t("strict"),
                description: t("strictDescription"),
                disabled: !isAdmin || (!data.eu_strict_available && data.data_residency !== "eu_strict"),
              },
            ]}
          />
          {!data.eu_strict_available && data.data_residency !== "eu_strict" ? (
            <Alert
              tone="warning"
              title={te("upgrade.title")}
              action={
                <Button asChild size="sm" variant="dark">
                  <Link href={billingHref(data.eu_strict_upgrade_to)}>
                    {te("upgrade.seePlans")}
                    <ArrowUpRight />
                  </Link>
                </Button>
              }
            >
              {te("upgrade.euStrict")}
            </Alert>
          ) : null}
          {mode === "eu_strict" && !bedrockReady ? <Alert tone="warning">{t("bedrockMissing")}</Alert> : null}
          <Field label={t("region")} hint={t("regionHint")} className="max-w-xs">
            <Select
              value={region}
              onValueChange={setRegion}
              disabled={!isAdmin}
              options={data.regions.map((r) => ({ value: r.id, label: `${r.name} (${r.id})` }))}
            />
          </Field>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title={t("bedrock")}
          description={t("bedrockDescription")}
          actions={
            bedrockReady ? (
              <Badge tone="success">
                <StatusDot tone="success" /> {t("bedrockAvailable", { region: data.bedrock.region })}
              </Badge>
            ) : (
              <Badge tone="warning">
                <StatusDot tone="warning" /> {t("bedrockNotConfigured")}
              </Badge>
            )
          }
        />
        {data.bedrock.models.length > 0 ? (
          <Table>
            <THead>
              <tr>
                <TH>{t("model")}</TH>
                <TH>{t("bedrockId")}</TH>
              </tr>
            </THead>
            <TBody>
              {data.bedrock.models.map((m) => (
                <TR key={m.model}>
                  <TD className="font-mono text-xs">{m.model}</TD>
                  <TD className="font-mono text-xs text-fg-muted">{m.bedrock_id}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        ) : null}
        <p className="px-4 py-3 text-xs text-fg-subtle">{t("bedrockRegions", { regions: data.bedrock.allowed_regions.join(", ") })}</p>
      </Card>

      <Card>
        <CardHeader title={t("providers")} description={t("providersDescription")} />
        <Table>
          <THead>
            <tr>
              <TH>{t("kindLabel")}</TH>
              <TH>{t("provider")}</TH>
              <TH className="hidden sm:table-cell">{t("regionShort")}</TH>
              <TH>{t("allowedStrict")}</TH>
              <TH>{t("active")}</TH>
            </tr>
          </THead>
          <TBody>
            {data.providers.map((p) => (
              <TR key={`${p.kind}:${p.provider}`}>
                <TD>{t(`kind.${p.kind}`)}</TD>
                <TD className="font-mono text-xs">{p.provider}</TD>
                <TD className="hidden text-fg-muted sm:table-cell">{p.region ?? "—"}</TD>
                <TD>{p.allowed_in_eu_strict ? <Badge tone="success">{tc("yes")}</Badge> : <Badge tone="danger">{tc("no")}</Badge>}</TD>
                <TD>{p.active ? <Badge tone="success">{tc("yes")}</Badge> : <Badge tone="neutral">{t("blocked")}</Badge>}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Card>

      <Card>
        <CardHeader title={t("retention")} description={t("retentionDescription")} />
        <CardBody className="grid gap-4 sm:grid-cols-2">
          <Field
            label={t("traceDays")}
            htmlFor="trace-days"
            hint={t("daysHint")}
            error={validDays(traceDays) ? undefined : t("daysInvalid")}
          >
            <Input
              id="trace-days"
              inputMode="numeric"
              value={traceDays}
              disabled={!isAdmin}
              aria-invalid={!validDays(traceDays)}
              onChange={(e) => setTraceDays(e.target.value.trim())}
            />
          </Field>
          <Field
            label={t("conversationDays")}
            htmlFor="conversation-days"
            hint={t("daysHint")}
            error={validDays(conversationDays) ? undefined : t("daysInvalid")}
          >
            <Input
              id="conversation-days"
              inputMode="numeric"
              value={conversationDays}
              disabled={!isAdmin}
              aria-invalid={!validDays(conversationDays)}
              onChange={(e) => setConversationDays(e.target.value.trim())}
            />
          </Field>
          <p className="text-xs text-fg-muted sm:col-span-2">
            {data.retention.last_purge_at
              ? t("lastPurge", {
                  date: formatDate(data.retention.last_purge_at, locale, true),
                  runs: formatNumber(lastPurge?.runs ?? 0, locale),
                  conversations: formatNumber(lastPurge?.conversations ?? 0, locale),
                })
              : t("neverPurged")}
          </p>
        </CardBody>
        {isAdmin ? (
          <CardFooter>
            <Button variant="primary" disabled={!canSave} loading={save.isPending} onClick={submit}>
              {tc("save")}
            </Button>
          </CardFooter>
        ) : null}
      </Card>

      <ConfirmDialog
        open={confirmStrict}
        onOpenChange={setConfirmStrict}
        title={t("confirmStrictTitle")}
        description={t("confirmStrictDescription")}
        confirmLabel={t("confirmStrict")}
        cancelLabel={tc("cancel")}
        destructive={false}
        loading={save.isPending}
        onConfirm={() => save.mutate()}
      />
    </div>
  );
}
