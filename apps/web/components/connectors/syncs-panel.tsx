"use client";

import {
  Alert,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  SkeletonRows,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  toast,
} from "@messer/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";
import { formatDuration, formatRelative, localeTag } from "@/lib/format";
import { useRole } from "@/lib/hooks/use-me";

import { StatusBadge } from "./connector-icon";
import { errorMessage, useSyncs } from "./queries";
import { SyncEditor } from "./sync-editor";
import type { Connection, SyncItem } from "./types";

function StatsLine({ sync }: { sync: SyncItem }) {
  const t = useTranslations("connectors.syncs.stats");
  const last = sync.stats.last_run;
  if (!last) return null;
  const parts: string[] = [];
  if (last.rows_upserted) parts.push(t("rows", { count: last.rows_upserted }));
  if (last.files_ingested !== undefined && (last.files_ingested > 0 || !last.rows_upserted)) {
    parts.push(t("files", { count: last.files_ingested }));
  }
  if (last.skipped) parts.push(t("skipped", { count: last.skipped }));
  if (last.pruned) parts.push(t("pruned", { count: last.pruned }));
  if (last.files_failed) parts.push(t("failed", { count: last.files_failed }));
  if (last.duration_ms !== undefined) parts.push(formatDuration(last.duration_ms));
  return <span className="tabular block text-xs text-fg-subtle">{parts.join(" · ")}</span>;
}

export function SyncsPanel({ connection }: { connection: Connection }) {
  const t = useTranslations("connectors.syncs");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const canEdit = useRole("builder");
  const syncs = useSyncs(connection.id);
  const [editing, setEditing] = React.useState<SyncItem | null>(null);
  const [creating, setCreating] = React.useState(false);
  const [deleting, setDeleting] = React.useState<SyncItem | null>(null);

  const run = useMutation({
    mutationFn: (id: string) => http.post<SyncItem>(`/syncs/${id}/run`),
    onSuccess: () => {
      toast.success(t("queued"));
      void qc.invalidateQueries({ queryKey: ["syncs"] });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });
  const remove = useMutation({
    mutationFn: (id: string) => http.del(`/syncs/${id}`),
    onSuccess: () => {
      toast.success(t("deleted"));
      setDeleting(null);
      void qc.invalidateQueries({ queryKey: ["syncs"] });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const header = canEdit ? (
    <div className="flex justify-end">
      <Button variant="primary" onClick={() => setCreating(true)}>
        <Plus />
        {t("new")}
      </Button>
    </div>
  ) : null;

  let body: React.ReactNode;
  if (syncs.isLoading) body = <SkeletonRows rows={3} />;
  else if (syncs.error) {
    body = <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void syncs.refetch()} retryLabel={tc("retry")} />;
  } else if ((syncs.data ?? []).length === 0) {
    body = <EmptyState icon={<RefreshCw />} title={t("empty")} description={t("emptyHint")} />;
  } else {
    body = (
      <Card>
        <Table>
          <THead>
            <tr>
              <TH>{t("resource")}</TH>
              <TH className="hidden md:table-cell">{t("kb")}</TH>
              <TH className="hidden lg:table-cell">{t("schedule")}</TH>
              <TH>{tc("status")}</TH>
              <TH className="hidden md:table-cell">{t("lastRun")}</TH>
              <TH className="w-56" />
            </tr>
          </THead>
          <TBody>
            {(syncs.data ?? []).map((s) => (
              <TR key={s.id}>
                <TD>
                  <span className="block max-w-xs truncate font-mono text-xs">{s.resource}</span>
                  <span className="text-xs text-fg-subtle">
                    {t(`modes.${s.mode}`)}
                    {s.cursor_field ? ` · ${s.cursor_field}` : ""}
                  </span>
                </TD>
                <TD className="hidden md:table-cell">
                  <Link href={`/app/knowledge/${s.kb_id}`} className="hover:underline">
                    {s.kb_name ?? s.kb_id}
                  </Link>
                </TD>
                <TD className="hidden font-mono text-xs text-fg-muted lg:table-cell">
                  {s.schedule ?? t("schedules.manual")}
                  {s.next_run_at ? (
                    <span className="block font-sans text-fg-subtle">
                      {t("nextRun")}: {formatRelative(s.next_run_at, locale)}
                    </span>
                  ) : null}
                </TD>
                <TD>
                  <StatusBadge status={s.status} />
                  {s.last_error ? <span className="mt-1 block max-w-xs truncate text-xs text-danger">{s.last_error}</span> : null}
                </TD>
                <TD className="hidden md:table-cell">
                  <span className="text-fg-muted">{s.last_run_at ? formatRelative(s.last_run_at, locale) : t("never")}</span>
                  <StatsLine sync={s} />
                </TD>
                <TD className="text-right">
                  {canEdit ? (
                    <div className="flex justify-end gap-1">
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={s.status === "queued" || s.status === "running"}
                        loading={run.isPending && run.variables === s.id}
                        onClick={() => run.mutate(s.id)}
                      >
                        {t("runNow")}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setEditing(s)}>
                        {tc("edit")}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setDeleting(s)}>
                        {t("delete")}
                      </Button>
                    </div>
                  ) : null}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {header}
      {(syncs.data ?? []).some((s) => (s.stats.last_run?.file_errors ?? []).length > 0) ? (
        <Alert tone="warning">
          {(syncs.data ?? [])
            .flatMap((s) => s.stats.last_run?.file_errors ?? [])
            .slice(0, 3)
            .map((e) => `${e.filename}: ${e.error}`)
            .join(" · ")}
        </Alert>
      ) : null}
      {body}
      <SyncEditor connection={connection} sync={null} open={creating} onOpenChange={setCreating} />
      <SyncEditor connection={connection} sync={editing} open={editing !== null} onOpenChange={(open) => !open && setEditing(null)} />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={t("deleteTitle")}
        description={t("deleteDescription")}
        confirmLabel={t("delete")}
        cancelLabel={tc("cancel")}
        loading={remove.isPending}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting.id);
        }}
      />
    </div>
  );
}
