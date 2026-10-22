"use client";

import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  type StatusTone,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  toast,
} from "@messer/ui";
import { useMutation } from "@tanstack/react-query";
import { Download, FileCheck2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { ApiError, http } from "@/lib/api";
import { formatDate, formatNumber, localeTag } from "@/lib/format";

import type { DataRequest } from "./types";

const STATUS_TONES: Record<DataRequest["status"], StatusTone> = {
  pending: "info",
  running: "info",
  completed: "success",
  failed: "danger",
  expired: "neutral",
};

export function DataRequestsTable({
  requests,
  currentUserId,
  canDownloadOrgReach,
  showSubject = true,
}: {
  requests: DataRequest[];
  currentUserId: string | undefined;
  canDownloadOrgReach: boolean;
  showSubject?: boolean;
}) {
  const t = useTranslations("enterprise.data");
  const locale = localeTag(useLocale());
  const [report, setReport] = React.useState<DataRequest | null>(null);
  const link = useMutation({
    mutationFn: (id: string) => http.post<{ url: string }>(`/data-requests/${id}/link`),
    onSuccess: (res) => window.location.assign(res.url),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });

  const canDownload = (r: DataRequest) =>
    r.file_ready &&
    (r.requester?.id === currentUserId || r.subject?.id === currentUserId || (canDownloadOrgReach && r.reach === "org"));

  return (
    <>
      <Table>
        <THead>
          <tr>
            <TH>{t("columns.request")}</TH>
            {showSubject ? <TH>{t("columns.subject")}</TH> : null}
            <TH className="hidden md:table-cell">{t("columns.requestedBy")}</TH>
            <TH>{t("columns.created")}</TH>
            <TH>{t("columns.status")}</TH>
            <TH className="w-36" />
          </tr>
        </THead>
        <TBody>
          {requests.map((r) => (
            <TR key={r.id}>
              <TD>
                <span className="font-medium">{t(`kind.${r.kind}`)}</span>
                <span className="block text-xs text-fg-subtle">
                  {r.scope === "org" ? t("scope.org") : r.reach === "account" ? t("accountWide") : t("orgOnly")}
                </span>
              </TD>
              {showSubject ? (
                <TD className="max-w-48 truncate">
                  {r.scope === "org" ? (r.org_name ?? "—") : (r.subject?.email ?? t("deletedPerson"))}
                </TD>
              ) : null}
              <TD className="hidden text-fg-muted md:table-cell">{r.requester?.email ?? "—"}</TD>
              <TD className="text-fg-muted">{formatDate(r.created_at, locale, true)}</TD>
              <TD>
                <Badge tone={STATUS_TONES[r.status]}>{t(`status.${r.status}`)}</Badge>
                {r.kind === "delete" && r.verified !== null ? (
                  <Badge tone={r.verified ? "success" : "danger"} className="ml-1">
                    {r.verified ? t("verified") : t("notVerified")}
                  </Badge>
                ) : null}
                {r.error ? <span className="mt-0.5 block text-xs text-danger">{r.error.message}</span> : null}
              </TD>
              <TD className="text-right">
                {canDownload(r) ? (
                  <Button size="sm" variant="secondary" loading={link.isPending && link.variables === r.id} onClick={() => link.mutate(r.id)}>
                    <Download />
                    {t("download")}
                  </Button>
                ) : null}
                {r.kind === "delete" && r.report.deletion ? (
                  <Button size="sm" variant="ghost" onClick={() => setReport(r)}>
                    <FileCheck2 />
                    {t("report")}
                  </Button>
                ) : null}
                {r.file_ready && r.expires_at ? (
                  <span className="block text-xs text-fg-subtle">{t("expires", { date: formatDate(r.expires_at, locale) })}</span>
                ) : null}
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
      <DeletionReportDialog request={report} onClose={() => setReport(null)} />
    </>
  );
}

function DeletionReportDialog({ request, onClose }: { request: DataRequest | null; onClose: () => void }) {
  const t = useTranslations("enterprise.data");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const deletion = request?.report.deletion;
  const rows = (obj: Record<string, number> | undefined) => Object.entries(obj ?? {}).sort(([a], [b]) => a.localeCompare(b));
  return (
    <Dialog open={request !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        wide
        title={t("reportTitle")}
        description={request?.completed_at ? formatDate(request.completed_at, locale, true) : undefined}
        footer={
          <Button variant="primary" onClick={onClose}>
            {tc("close")}
          </Button>
        }
      >
        {deletion ? (
          <div className="flex flex-col gap-4 text-sm">
            <Badge tone={deletion.verified ? "success" : "danger"} className="w-fit">
              {deletion.verified ? t("verifiedLong") : t("notVerified")}
            </Badge>
            <section>
              <h3 className="mb-1 font-semibold">{t("deletedRows")}</h3>
              <CountList rows={rows(deletion.deleted)} empty={t("none")} locale={locale} />
            </section>
            {Object.keys(deletion.anonymized ?? {}).length > 0 ? (
              <section>
                <h3 className="mb-1 font-semibold">{t("anonymized")}</h3>
                <CountList rows={rows(deletion.anonymized)} empty={t("none")} locale={locale} />
              </section>
            ) : null}
            <section>
              <h3 className="mb-1 font-semibold">{t("postChecks")}</h3>
              <ul className="flex flex-col divide-y divide-border rounded-md border border-border">
                {(deletion.post_checks ?? []).map((c) => (
                  <li key={c.check} className="flex items-start justify-between gap-3 px-3 py-1.5">
                    <span className="min-w-0">
                      <span className="block font-mono text-xs">{c.check}</span>
                      <code className="block break-all text-[11px] text-fg-subtle">{c.sql}</code>
                    </span>
                    <Badge tone={c.remaining === 0 ? "success" : "danger"}>{t("remaining", { count: c.remaining })}</Badge>
                  </li>
                ))}
              </ul>
            </section>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function CountList({ rows, empty, locale }: { rows: [string, number][]; empty: string; locale: string }) {
  if (rows.length === 0) return <p className="text-fg-subtle">{empty}</p>;
  return (
    <ul className="grid gap-x-4 gap-y-0.5 sm:grid-cols-2">
      {rows.map(([name, count]) => (
        <li key={name} className="flex justify-between gap-2 font-mono text-xs">
          <span className="truncate">{name}</span>
          <span className="tabular">{formatNumber(count, locale)}</span>
        </li>
      ))}
    </ul>
  );
}
