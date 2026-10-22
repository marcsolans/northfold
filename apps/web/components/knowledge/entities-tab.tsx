"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  Dialog,
  DialogContent,
  EmptyState,
  ErrorState,
  Select,
  SkeletonRows,
  toast,
} from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { GitMerge, Play, Users, X } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";
import { formatRelative, localeTag } from "@/lib/format";

import { errorMessage, formatCell, kbKeys } from "./queries";
import type { EntityList, KbEntity, KnowledgeBase } from "./types";

type StatusFilter = "suggested" | "merged" | "dismissed" | "all";

function fieldsOf(entity: KbEntity): string[] {
  const out: string[] = [];
  for (const record of entity.records) {
    for (const key of Object.keys(record.values)) if (!out.includes(key)) out.push(key);
  }
  return out;
}

function MergeDialog({ kbId, entity, onClose }: { kbId: string; entity: KbEntity | null; onClose: () => void }) {
  const t = useTranslations("knowledge.entities");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const [choice, setChoice] = React.useState<Record<string, string>>({});
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!entity) return;
    const initial: Record<string, string> = {};
    for (const field of fieldsOf(entity)) {
      const index = entity.records.findIndex((r) => r.values[field] !== null && r.values[field] !== undefined && r.values[field] !== "");
      initial[field] = String(Math.max(0, index));
    }
    setChoice(initial);
    setError(null);
  }, [entity]);

  const merge = useMutation({
    mutationFn: () => {
      if (!entity) throw new Error("no entity");
      const golden: Record<string, unknown> = {};
      for (const field of fieldsOf(entity)) {
        const record = entity.records[Number(choice[field] ?? 0)];
        const value = record?.values[field];
        if (value !== null && value !== undefined && value !== "") golden[field] = value;
      }
      return http.post<KbEntity>(`/knowledge-bases/${kbId}/entities/${entity.id}/merge`, { golden_record: golden });
    },
    onSuccess: () => {
      toast.success(t("mergedToast"));
      void qc.invalidateQueries({ queryKey: kbKeys.entities(kbId) });
      onClose();
    },
    onError: (err) => setError(errorMessage(err)),
  });

  return (
    <Dialog open={entity !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent wide title={t("mergeTitle")} description={t("mergeDescription")}>
        {entity ? (
          <div className="flex flex-col gap-3">
            {error ? <Alert tone="danger">{error}</Alert> : null}
            <div className="grid gap-2">
              {fieldsOf(entity).map((field) => (
                <div key={field} className="grid grid-cols-[10rem_minmax(0,1fr)] items-center gap-2">
                  <span className="truncate font-mono text-xs text-fg-muted">{field}</span>
                  <Select
                    aria-label={field}
                    value={choice[field] ?? "0"}
                    onValueChange={(v) => setChoice((c) => ({ ...c, [field]: v }))}
                    options={entity.records.map((r, i) => ({
                      value: String(i),
                      label: formatCell(r.values[field]) || t("emptyValue"),
                      description: `${r.table} · ${Object.values(r.pk).map(formatCell).join(", ")}`,
                    }))}
                  />
                </div>
              ))}
            </div>
            <div className="mt-2 flex justify-end gap-2">
              <Button variant="secondary" onClick={onClose}>
                {tc("cancel")}
              </Button>
              <Button variant="primary" loading={merge.isPending} onClick={() => merge.mutate()}>
                <GitMerge />
                {t("merge")}
              </Button>
            </div>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

export function EntitiesTab({ kb, canWrite }: { kb: KnowledgeBase; canWrite: boolean }) {
  const t = useTranslations("knowledge.entities");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const [status, setStatus] = React.useState<StatusFilter>("suggested");
  const [merging, setMerging] = React.useState<KbEntity | null>(null);
  const entities = useQuery({
    queryKey: [...kbKeys.entities(kb.id), status],
    queryFn: () => http.get<EntityList>(`/knowledge-bases/${kb.id}/entities`, { status, limit: 100 }),
  });
  const run = useMutation({
    mutationFn: () => http.post(`/knowledge-bases/${kb.id}/entities/run`),
    onSuccess: () => toast.success(t("queued")),
    onError: (err) => toast.error(errorMessage(err)),
  });
  const dismiss = useMutation({
    mutationFn: (entity: KbEntity) => http.post<KbEntity>(`/knowledge-bases/${kb.id}/entities/${entity.id}/dismiss`),
    onSuccess: () => {
      toast.success(t("dismissedToast"));
      void qc.invalidateQueries({ queryKey: kbKeys.entities(kb.id) });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const filters: StatusFilter[] = ["suggested", "merged", "dismissed", "all"];
  const items = entities.data?.items ?? [];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-1" role="group" aria-label={tc("status")}>
          {filters.map((f) => (
            <Button key={f} size="sm" variant={status === f ? "dark" : "ghost"} aria-pressed={status === f} onClick={() => setStatus(f)}>
              {t(`filter.${f}`)}
            </Button>
          ))}
        </div>
        {canWrite ? (
          <Button size="sm" variant="secondary" loading={run.isPending} onClick={() => run.mutate()}>
            <Play />
            {t("run")}
          </Button>
        ) : null}
      </div>
      <p className="text-xs text-fg-subtle">{t("description")}</p>
      {entities.isLoading ? (
        <SkeletonRows rows={4} />
      ) : entities.error ? (
        <ErrorState title={tc("errorTitle")} description={errorMessage(entities.error)} onRetry={() => void entities.refetch()} retryLabel={tc("retry")} />
      ) : items.length === 0 ? (
        <EmptyState icon={<Users />} title={t("empty")} description={t("emptyHint")} />
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map((entity) => {
            const [kind, ...rest] = entity.match_key.split(":");
            const keyValue = rest.join(":");
            const fields = fieldsOf(entity).slice(0, 6);
            return (
              <li key={entity.id}>
                <Card className="flex flex-col gap-3 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="flex flex-wrap items-center gap-2 text-sm">
                      <Badge tone={entity.method === "deterministic" ? "info" : "warning"}>{t(`method.${entity.method === "deterministic" ? "deterministic" : "similarity"}`)}</Badge>
                      <span className="text-xs text-fg-muted">{t(`keys.${kind === "tax_id" || kind === "email" || kind === "domain" ? kind : "similar"}`)}</span>
                      <span className="font-mono text-xs">{keyValue}</span>
                      <Badge tone="outline">{t(`types.${entity.entity_type === "company" || entity.entity_type === "person" ? entity.entity_type : "generic"}`)}</Badge>
                      <span className="tabular text-xs text-fg-subtle">{t("score", { score: Math.round(entity.score * 100) })}</span>
                    </span>
                    <span className="flex items-center gap-1">
                      {entity.status === "suggested" && canWrite ? (
                        <>
                          <Button size="sm" variant="ghost" loading={dismiss.isPending && dismiss.variables?.id === entity.id} onClick={() => dismiss.mutate(entity)}>
                            <X />
                            {t("dismiss")}
                          </Button>
                          <Button size="sm" variant="dark" onClick={() => setMerging(entity)}>
                            <GitMerge />
                            {t("merge")}
                          </Button>
                        </>
                      ) : entity.status !== "suggested" ? (
                        <span className="text-xs text-fg-subtle">
                          {t(`status.${entity.status}`)}
                          {entity.decided_at ? ` · ${formatRelative(entity.decided_at, locale)}` : ""}
                        </span>
                      ) : null}
                    </span>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b border-border text-left text-fg-subtle">
                          <th className="py-1 pr-3 font-medium">{t("source")}</th>
                          {fields.map((f) => (
                            <th key={f} className="py-1 pr-3 font-mono font-medium">
                              {f}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {entity.records.map((r, i) => (
                          <tr key={i} className="border-b border-border last:border-0">
                            <td className="py-1 pr-3 font-mono text-fg-muted">
                              {r.table} · {Object.values(r.pk).map(formatCell).join(", ")}
                            </td>
                            {fields.map((f) => (
                              <td key={f} className="max-w-48 truncate py-1 pr-3">
                                {formatCell(r.values[f])}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {entity.status === "merged" && entity.golden_record ? (
                    <div className="rounded-md border border-success/25 bg-success-soft p-2 text-xs">
                      <p className="mb-1 font-semibold text-success">{t("golden")}</p>
                      <p className="text-fg">
                        {Object.entries(entity.golden_record.fields)
                          .map(([k, v]) => `${k}: ${formatCell(v)}`)
                          .join(" · ")}
                      </p>
                    </div>
                  ) : null}
                </Card>
              </li>
            );
          })}
        </ul>
      )}
      <MergeDialog kbId={kb.id} entity={merging} onClose={() => setMerging(null)} />
    </div>
  );
}
