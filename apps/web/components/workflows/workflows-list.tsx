"use client";

import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
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
  toast,
} from "@messer/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, Workflow } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { RunStatusBadge } from "@/components/traces/run-status-badge";
import { http } from "@/lib/api";
import { formatRelative, localeTag } from "@/lib/format";
import { useRole } from "@/lib/hooks/use-me";
import { errorMessage, studioKeys } from "@/lib/studio/hooks";
import { useWorkflows, workflowKeys } from "@/lib/workflows/hooks";
import type { WorkflowSummary } from "@/lib/workflows/types";

import { CreateWorkflowDialog } from "./create-workflow-dialog";

export function WorkflowsList({ projectId }: { projectId: string }) {
  const t = useTranslations("workflows.list");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const canBuild = useRole("builder");
  const qc = useQueryClient();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const workflows = useWorkflows(projectId);
  const [createOpen, setCreateOpen] = React.useState(false);
  const [deleting, setDeleting] = React.useState<WorkflowSummary | null>(null);

  React.useEffect(() => {
    if (params.get("new") === "1" && canBuild) {
      setCreateOpen(true);
      router.replace(pathname);
    }
  }, [params, canBuild, router, pathname]);

  const remove = useMutation({
    mutationFn: (name: string) => http.del(`/projects/${projectId}/workforce/${encodeURIComponent(name)}`),
    onSuccess: (_, name) => {
      setDeleting(null);
      toast.success(t("deleted", { name }));
      void qc.invalidateQueries({ queryKey: workflowKeys.list(projectId) });
      void qc.invalidateQueries({ queryKey: workflowKeys.triggers(projectId) });
      void qc.invalidateQueries({ queryKey: studioKeys.project(projectId) });
    },
    onError: (err) => toast.error(errorMessage(err, tc("errorGeneric"))),
  });

  const createButton = canBuild ? (
    <Button variant="primary" onClick={() => setCreateOpen(true)}>
      <Plus />
      {t("new")}
    </Button>
  ) : null;
  const list = workflows.data ?? [];

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-6 md:px-6">
      <PageHeader title={t("title")} description={t("description")} actions={createButton} />
      {workflows.isLoading ? (
        <Card className="p-4">
          <SkeletonRows rows={4} />
        </Card>
      ) : workflows.error ? (
        <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void workflows.refetch()} retryLabel={tc("retry")} />
      ) : list.length === 0 ? (
        <EmptyState icon={<Workflow />} title={t("empty.title")} description={t("empty.description")} action={createButton} />
      ) : (
        <Card>
          <Table>
            <THead>
              <tr>
                <TH>{tc("name")}</TH>
                <TH className="hidden md:table-cell">{tc("description")}</TH>
                <TH className="hidden sm:table-cell">{t("columns.nodes")}</TH>
                <TH className="hidden sm:table-cell">{t("columns.triggers")}</TH>
                <TH>{t("columns.lastRun")}</TH>
                <TH>{t("columns.version")}</TH>
                <TH className="hidden lg:table-cell">{tc("updated")}</TH>
                {canBuild ? <TH className="w-12" /> : null}
              </tr>
            </THead>
            <TBody>
              {list.map((wf) => (
                <TR key={wf.id}>
                  <TD>
                    <Link
                      href={`/app/projects/${projectId}/workflows/${encodeURIComponent(wf.name)}`}
                      className="flex items-center gap-2 font-mono text-xs font-medium hover:underline"
                    >
                      <Workflow className="size-4 text-fg-subtle" aria-hidden />
                      {wf.name}
                    </Link>
                  </TD>
                  <TD className="hidden max-w-sm truncate text-fg-muted md:table-cell">{wf.description || "—"}</TD>
                  <TD className="hidden tabular sm:table-cell">{wf.source_mode === "code" ? "—" : wf.nodes}</TD>
                  <TD className="hidden tabular sm:table-cell">{wf.triggers}</TD>
                  <TD>
                    {wf.last_run ? (
                      <Link href={`/app/projects/${projectId}/traces/${wf.last_run.id}`} className="inline-flex items-center gap-1.5">
                        <RunStatusBadge status={wf.last_run.status} />
                        <span className="hidden text-xs text-fg-muted xl:inline">{formatRelative(wf.last_run.started_at, locale)}</span>
                      </Link>
                    ) : (
                      <span className="text-xs text-fg-subtle">{t("never")}</span>
                    )}
                  </TD>
                  <TD>
                    <span className="flex items-center gap-1.5">
                      <Badge tone="outline">v{wf.current_version}</Badge>
                      {wf.source_mode === "code" ? <Badge tone="info">{t("codeMode")}</Badge> : null}
                    </span>
                  </TD>
                  <TD className="hidden text-fg-muted lg:table-cell">{formatRelative(wf.updated_at, locale)}</TD>
                  {canBuild ? (
                    <TD className="text-right">
                      <Button variant="ghost" size="icon-sm" aria-label={t("delete", { name: wf.name })} onClick={() => setDeleting(wf)}>
                        <Trash2 />
                      </Button>
                    </TD>
                  ) : null}
                </TR>
              ))}
            </TBody>
          </Table>
        </Card>
      )}
      <CreateWorkflowDialog projectId={projectId} open={createOpen} onOpenChange={setCreateOpen} existing={list.map((w) => w.name)} />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
        title={t("deleteTitle", { name: deleting?.name ?? "" })}
        description={t("deleteDescription")}
        confirmLabel={tc("delete")}
        cancelLabel={tc("cancel")}
        destructive
        loading={remove.isPending}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting.name);
        }}
      />
    </div>
  );
}
