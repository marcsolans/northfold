"use client";

import {
  Badge,
  Button,
  Card,
  CardHeader,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  SkeletonRows,
  type StatusTone,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  toast,
} from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, Plus, RotateCcw, Trash2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";
import { formatDate, localeTag } from "@/lib/format";

import { errorMessage, formatBytes, kbKeys } from "./queries";
import type { KbBackup, KnowledgeBase } from "./types";

const TONES: Record<KbBackup["status"], StatusTone> = {
  pending: "neutral",
  running: "info",
  ready: "success",
  error: "danger",
  restoring: "warning",
};

function num(value: unknown): number {
  return typeof value === "number" ? value : 0;
}

export function BackupsTab({ kb, isAdmin }: { kb: KnowledgeBase; isAdmin: boolean }) {
  const t = useTranslations("knowledge.backups");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const [restoring, setRestoring] = React.useState<KbBackup | null>(null);
  const [deleting, setDeleting] = React.useState<KbBackup | null>(null);
  const backups = useQuery({
    queryKey: kbKeys.backups(kb.id),
    queryFn: () => http.get<KbBackup[]>(`/knowledge-bases/${kb.id}/backups`),
    refetchInterval: (query) =>
      (query.state.data ?? []).some((b) => b.status === "pending" || b.status === "running" || b.status === "restoring")
        ? 3000
        : false,
  });
  const invalidate = () => void qc.invalidateQueries({ queryKey: kbKeys.backups(kb.id) });
  const create = useMutation({
    mutationFn: () => http.post<KbBackup>(`/knowledge-bases/${kb.id}/backups`),
    onSuccess: () => {
      toast.success(t("queued"));
      invalidate();
    },
    onError: (err) => toast.error(errorMessage(err)),
  });
  const restore = useMutation({
    mutationFn: (b: KbBackup) => http.post<KbBackup>(`/knowledge-bases/${kb.id}/backups/${b.id}/restore`),
    onSuccess: () => {
      toast.success(t("restoreQueued"));
      setRestoring(null);
      invalidate();
    },
    onError: (err) => toast.error(errorMessage(err)),
  });
  const remove = useMutation({
    mutationFn: (b: KbBackup) => http.del(`/knowledge-bases/${kb.id}/backups/${b.id}`),
    onSuccess: () => {
      toast.success(t("deleted"));
      setDeleting(null);
      invalidate();
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const busy = (backups.data ?? []).some((b) => b.status === "pending" || b.status === "running" || b.status === "restoring");

  return (
    <Card>
      <CardHeader
        title={t("title")}
        description={t("description")}
        actions={
          isAdmin ? (
            <Button size="sm" variant="primary" loading={create.isPending} disabled={busy} onClick={() => create.mutate()}>
              <Plus />
              {t("create")}
            </Button>
          ) : null
        }
      />
      {backups.isLoading ? (
        <div className="p-4">
          <SkeletonRows rows={3} />
        </div>
      ) : backups.error ? (
        <div className="p-4">
          <ErrorState title={tc("errorTitle")} description={errorMessage(backups.error)} onRetry={() => void backups.refetch()} retryLabel={tc("retry")} />
        </div>
      ) : (backups.data ?? []).length === 0 ? (
        <div className="p-4">
          <EmptyState icon={<Archive />} title={t("empty")} description={t("emptyHint")} />
        </div>
      ) : (
        <Table>
          <THead>
            <tr>
              <TH>{tc("created")}</TH>
              <TH>{tc("status")}</TH>
              <TH className="hidden md:table-cell">{t("contents")}</TH>
              <TH className="hidden md:table-cell">{t("size")}</TH>
              <TH className="hidden lg:table-cell">{t("restoredAt")}</TH>
              <TH className="w-24" />
            </tr>
          </THead>
          <TBody>
            {(backups.data ?? []).map((b) => (
              <TR key={b.id}>
                <TD className="tabular">{formatDate(b.created_at, locale, true)}</TD>
                <TD>
                  <span className="flex flex-col gap-0.5">
                    <Badge tone={TONES[b.status]} className="self-start">
                      {t(`status.${b.status}`)}
                    </Badge>
                    {typeof b.stats.error === "string" ? <span className="text-xs text-danger">{b.stats.error}</span> : null}
                    {typeof b.stats.last_restore_error === "string" ? (
                      <span className="text-xs text-danger">{b.stats.last_restore_error}</span>
                    ) : null}
                  </span>
                </TD>
                <TD className="tabular hidden text-xs text-fg-muted md:table-cell">
                  {b.status === "ready" || b.restored_at
                    ? t("stats", {
                        tables: num(b.stats.tables),
                        rows: num(b.stats.rows),
                        files: num(b.stats.files),
                        chunks: num(b.stats.chunks),
                      })
                    : "—"}
                </TD>
                <TD className="tabular hidden text-fg-muted md:table-cell">{b.size ? formatBytes(b.size, locale) : "—"}</TD>
                <TD className="hidden text-fg-muted lg:table-cell">{b.restored_at ? formatDate(b.restored_at, locale, true) : "—"}</TD>
                <TD className="text-right">
                  {isAdmin ? (
                    <span className="flex justify-end gap-1">
                      <Button size="sm" variant="ghost" disabled={b.status !== "ready" || busy} onClick={() => setRestoring(b)}>
                        <RotateCcw />
                        {t("restore")}
                      </Button>
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        aria-label={tc("delete")}
                        disabled={b.status === "running" || b.status === "restoring"}
                        onClick={() => setDeleting(b)}
                      >
                        <Trash2 />
                      </Button>
                    </span>
                  ) : null}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}
      <ConfirmDialog
        open={restoring !== null}
        onOpenChange={(open) => !open && setRestoring(null)}
        title={t("restoreConfirm")}
        description={t("restoreDescription", { date: restoring ? formatDate(restoring.created_at, locale, true) : "" })}
        confirmLabel={t("restore")}
        cancelLabel={tc("cancel")}
        loading={restore.isPending}
        onConfirm={() => {
          if (restoring) restore.mutate(restoring);
        }}
      />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={t("deleteConfirm")}
        description={t("deleteDescription")}
        confirmLabel={tc("delete")}
        cancelLabel={tc("cancel")}
        loading={remove.isPending}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting);
        }}
      />
    </Card>
  );
}
