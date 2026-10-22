"use client";

import {
  Badge,
  Card,
  CardBody,
  CardHeader,
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
} from "@messer/ui";
import { useQuery } from "@tanstack/react-query";
import { Cpu } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { http } from "@/lib/api";
import { formatNumber, formatUsd, localeTag } from "@/lib/format";

type Model = {
  model: string;
  display_name: string;
  provider: string;
  input_per_mtok_usd: string;
  output_per_mtok_usd: string;
  context_window: number | null;
  eu_bedrock: boolean;
  allowed: boolean;
  tiers: string[];
};
type ModelsResponse = { tiers: Record<string, string>; models: Model[] };

const TIER_ORDER = ["fast", "standard", "powerful"];

/** Model catalog for the organization: tiers, prices per million tokens, EU availability and policy. */
export default function ModelsSettingsPage() {
  const t = useTranslations("models");
  const ts = useTranslations("settings.sections");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const models = useQuery({ queryKey: ["models"], queryFn: () => http.get<ModelsResponse>("/models") });

  const header = <PageHeader title={ts("models")} description={t("description")} />;
  if (models.isLoading) {
    return (
      <div className="flex flex-col gap-6">
        {header}
        <SkeletonRows rows={6} />
      </div>
    );
  }
  if (models.error || !models.data) {
    return (
      <div className="flex flex-col gap-6">
        {header}
        <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void models.refetch()} />
      </div>
    );
  }
  const { tiers, models: rows } = models.data;
  const byId = new Map(rows.map((m) => [m.model, m]));
  const tierKeys = Object.keys(tiers).sort((a, b) => TIER_ORDER.indexOf(a) - TIER_ORDER.indexOf(b));

  return (
    <div className="flex flex-col gap-6">
      {header}
      <Card>
        <CardHeader title={t("tiers.title")} description={t("tiers.description")} />
        <CardBody className="grid gap-3 sm:grid-cols-3">
          {tierKeys.map((tier) => {
            const id = tiers[tier] ?? "";
            return (
              <div key={tier} className="rounded-md border border-border p-3">
                <p className="text-xs font-medium uppercase tracking-wide text-fg-muted">
                  {TIER_ORDER.includes(tier) ? t(`tiers.names.${tier}`) : tier}
                </p>
                <p className="mt-1 font-medium">{byId.get(id)?.display_name ?? id}</p>
                <p className="text-xs text-fg-subtle">{t(TIER_ORDER.includes(tier) ? `tiers.hints.${tier}` : "tiers.hints.custom")}</p>
              </div>
            );
          })}
        </CardBody>
      </Card>
      <Card>
        <CardHeader title={t("catalog.title")} description={t("catalog.description")} />
        {rows.length === 0 ? (
          <div className="p-4">
            <EmptyState icon={<Cpu />} title={t("catalog.emptyTitle")} description={t("catalog.emptyDescription")} />
          </div>
        ) : (
          <Table>
            <THead>
              <tr>
                <TH>{t("catalog.model")}</TH>
                <TH className="text-right">{t("catalog.input")}</TH>
                <TH className="text-right">{t("catalog.output")}</TH>
                <TH className="hidden text-right md:table-cell">{t("catalog.context")}</TH>
                <TH>{t("catalog.availability")}</TH>
              </tr>
            </THead>
            <TBody>
              {rows.map((m) => (
                <TR key={m.model}>
                  <TD>
                    <span className="font-medium">{m.display_name}</span>
                    <span className="block font-mono text-xs text-fg-subtle">{m.model}</span>
                    {m.tiers.length ? (
                      <span className="mt-1 flex flex-wrap gap-1">
                        {m.tiers.map((tier) => (
                          <Badge key={tier} tone="info">
                            {TIER_ORDER.includes(tier) ? t(`tiers.names.${tier}`) : tier}
                          </Badge>
                        ))}
                      </span>
                    ) : null}
                  </TD>
                  <TD className="tabular text-right">{formatUsd(m.input_per_mtok_usd, locale)}</TD>
                  <TD className="tabular text-right">{formatUsd(m.output_per_mtok_usd, locale)}</TD>
                  <TD className="tabular hidden text-right text-fg-muted md:table-cell">
                    {m.context_window ? formatNumber(m.context_window, locale) : "—"}
                  </TD>
                  <TD>
                    <span className="flex flex-wrap gap-1">
                      <Badge tone={m.allowed ? "success" : "neutral"}>
                        {m.allowed ? t("catalog.allowed") : t("catalog.blocked")}
                      </Badge>
                      {m.eu_bedrock ? <Badge tone="info">{t("catalog.eu")}</Badge> : null}
                    </span>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    </div>
  );
}
