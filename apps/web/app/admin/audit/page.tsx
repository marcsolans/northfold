"use client";

import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Input,
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
import { ClipboardList, Search } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { ADMIN_KEY, type AdminAudit } from "@/components/admin/types";
import { http } from "@/lib/api";
import { formatDate, localeTag } from "@/lib/format";

function summarize(diff: Record<string, unknown>): string {
  const parts = Object.entries(diff)
    .filter(([, v]) => v !== null && v !== undefined && typeof v !== "object")
    .slice(0, 4)
    .map(([k, v]) => `${k}: ${String(v)}`);
  return parts.join(" · ");
}

export default function AdminAuditPage() {
  const t = useTranslations("admin");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const [action, setAction] = React.useState("admin.");
  const [applied, setApplied] = React.useState("admin.");
  const [limit, setLimit] = React.useState(100);
  const audit = useQuery({
    queryKey: [...ADMIN_KEY, "audit", applied, limit],
    queryFn: () => http.get<AdminAudit[]>("/admin/audit", { action: applied, limit }),
  });
  return (
    <div className="flex flex-col gap-4">
      <PageHeader title={t("audit.title")} description={t("audit.description")} />
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setApplied(action.trim());
        }}
      >
        <div className="relative w-full max-w-xs">
          <Search className="pointer-events-none absolute left-2.5 top-2 size-4 text-fg-subtle" aria-hidden />
          <Input className="pl-8 font-mono" aria-label={t("audit.action")} value={action} onChange={(e) => setAction(e.target.value)} />
        </div>
        <Button type="submit">{tc("search")}</Button>
        <p className="text-xs text-fg-subtle">{t("audit.prefixHint")}</p>
      </form>
      <Card>
        {audit.isLoading ? (
          <div className="p-4">
            <SkeletonRows rows={8} />
          </div>
        ) : audit.error || !audit.data ? (
          <div className="p-4">
            <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void audit.refetch()} />
          </div>
        ) : audit.data.length === 0 ? (
          <div className="p-4">
            <EmptyState icon={<ClipboardList />} title={t("audit.emptyTitle")} description={t("audit.empty")} />
          </div>
        ) : (
          <Table>
            <THead>
              <tr>
                <TH>{t("audit.date")}</TH>
                <TH>{t("audit.action")}</TH>
                <TH>{t("audit.actor")}</TH>
                <TH className="hidden md:table-cell">{t("audit.target")}</TH>
                <TH className="hidden lg:table-cell">{t("audit.details")}</TH>
              </tr>
            </THead>
            <TBody>
              {audit.data.map((a) => (
                <TR key={a.id}>
                  <TD className="whitespace-nowrap text-fg-muted">{formatDate(a.created_at, locale, true)}</TD>
                  <TD className="font-mono text-xs">{a.action}</TD>
                  <TD>
                    {a.actor_email ?? t("audit.system")}
                    {a.impersonated_by_email ? (
                      <span className="block text-xs text-fg-subtle">{t("audit.via", { email: a.impersonated_by_email })}</span>
                    ) : null}
                  </TD>
                  <TD className="hidden md:table-cell">
                    {a.org_id ? (
                      <Link href={`/admin/orgs/${a.org_id}`} className="text-sm hover:underline">
                        {t("audit.org")}
                      </Link>
                    ) : null}
                    {a.entity_type ? (
                      <span className="block font-mono text-xs text-fg-subtle">
                        {a.entity_type}
                        {a.entity_id ? `:${a.entity_id.slice(0, 18)}` : ""}
                      </span>
                    ) : null}
                  </TD>
                  <TD className="hidden max-w-md truncate text-xs text-fg-muted lg:table-cell">{summarize(a.diff)}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
      {audit.data && audit.data.length >= limit ? (
        <div className="flex justify-center">
          <Button onClick={() => setLimit((l) => Math.min(500, l + 100))} disabled={limit >= 500}>
            {t("audit.loadMore")}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
