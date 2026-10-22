"use client";

import { Button, ConfirmDialog, Dialog, DialogContent, EmptyState, ErrorState, SkeletonRows, cn, toast } from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { History } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { DiffViewer } from "@/components/studio/monaco";
import { http } from "@/lib/api";
import { formatDate, localeTag } from "@/lib/format";

import { interfaceKeys, useVersions } from "../api";
import type { InterfaceDefinition, InterfaceDetail, VersionInfo } from "../types";
import { messageOf } from "../util";

/** The commits that changed this interface; compare any of them with the current code and restore it. */
export function VersionsDialog({
  open,
  onOpenChange,
  interfaceId,
  current,
  canRestore,
  onRestored,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  interfaceId: string;
  current: InterfaceDefinition;
  canRestore: boolean;
  onRestored: (detail: InterfaceDetail) => void;
}) {
  const t = useTranslations("interfaces.versions");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const versions = useVersions(interfaceId, open);
  const [selected, setSelected] = React.useState<VersionInfo | null>(null);
  const [confirm, setConfirm] = React.useState(false);
  const version = useQuery({
    queryKey: interfaceKeys.version(interfaceId, selected?.sha ?? ""),
    queryFn: () => http.get<{ sha: string; definition: InterfaceDefinition }>(`/interfaces/${interfaceId}/versions/${selected?.sha}`),
    enabled: Boolean(selected),
  });
  const restore = useMutation({
    mutationFn: (sha: string) => http.post<InterfaceDetail>(`/interfaces/${interfaceId}/versions/${sha}/restore`),
    onSuccess: (detail) => {
      toast.success(t("restored"));
      setConfirm(false);
      onOpenChange(false);
      void qc.invalidateQueries({ queryKey: interfaceKeys.versions(interfaceId) });
      onRestored(detail);
    },
    onError: (err) => toast.error(messageOf(err, tc("errorGeneric"))),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={t("title")} description={t("description")} wide className="max-w-5xl">
        {versions.isPending ? (
          <SkeletonRows rows={4} />
        ) : versions.error ? (
          <ErrorState title={tc("errorTitle")} description={messageOf(versions.error, tc("errorGeneric"))} onRetry={() => void versions.refetch()} retryLabel={tc("retry")} />
        ) : versions.data.length === 0 ? (
          <EmptyState icon={<History />} title={t("emptyTitle")} description={t("emptyDescription")} />
        ) : (
          <div className="grid gap-3 md:grid-cols-[16rem_1fr]">
            <ul className="flex max-h-[60vh] flex-col gap-1 overflow-auto" aria-label={t("list")}>
              {versions.data.map((v, i) => (
                <li key={v.sha}>
                  <button
                    type="button"
                    onClick={() => setSelected(v)}
                    aria-pressed={selected?.sha === v.sha}
                    className={cn(
                      "w-full rounded-md border px-2.5 py-2 text-left text-sm",
                      selected?.sha === v.sha ? "border-fg bg-subtle" : "border-border hover:bg-subtle",
                    )}
                  >
                    <span className="block truncate font-medium text-fg">{v.message}</span>
                    <span className="block text-xs text-fg-muted">
                      {v.author} · {formatDate(v.date, locale, true)} · <span className="font-mono">{v.sha.slice(0, 8)}</span>
                      {i === 0 ? ` · ${t("current")}` : ""}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            <div className="flex min-h-80 flex-col gap-2">
              {!selected ? (
                <p className="m-auto text-sm text-fg-muted">{t("pick")}</p>
              ) : version.isPending ? (
                <SkeletonRows rows={6} />
              ) : version.error ? (
                <ErrorState title={tc("errorTitle")} description={messageOf(version.error, tc("errorGeneric"))} />
              ) : (
                <>
                  <div className="h-[50vh] overflow-hidden rounded-md border border-border">
                    <DiffViewer
                      original={JSON.stringify(version.data.definition, null, 2)}
                      modified={JSON.stringify(current, null, 2)}
                      language="json"
                      ariaLabel={t("diffLabel")}
                    />
                  </div>
                  <div className="flex items-center justify-between gap-2 text-xs text-fg-muted">
                    <span>{t("diffLegend")}</span>
                    {canRestore ? (
                      <Button size="sm" variant="secondary" onClick={() => setConfirm(true)}>
                        {t("restore")}
                      </Button>
                    ) : null}
                  </div>
                </>
              )}
            </div>
          </div>
        )}
        <ConfirmDialog
          open={confirm}
          onOpenChange={setConfirm}
          title={t("restoreTitle")}
          description={t("restoreDescription", { sha: selected?.sha.slice(0, 8) ?? "" })}
          confirmLabel={t("restore")}
          cancelLabel={tc("cancel")}
          loading={restore.isPending}
          onConfirm={() => (selected ? restore.mutateAsync(selected.sha).then(() => undefined) : undefined)}
        />
      </DialogContent>
    </Dialog>
  );
}
