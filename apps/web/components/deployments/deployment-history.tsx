"use client";

import {
  Button,
  Card,
  CardHeader,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Select,
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
import { History, Rocket, ScrollText, Undo2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { useUpgradeDialog } from "@/components/billing";
import { http } from "@/lib/api";
import { formatDate, formatRelative, localeTag } from "@/lib/format";
import { shortHash } from "@/lib/studio/format";
import type { Environment } from "@/lib/studio/types";

import { DeploymentStatusBadge, ForcedBadge, useEnvironmentLabel } from "./labels";
import { deploymentKeys, useApiErrorText, useDeploymentHistory, useMemberName } from "./queries";
import { type Deployment, ENVIRONMENTS, type EnvironmentName, isActive } from "./types";

const ALL = "all";

/** History of deployments (version, commit, who, when, status, forced) with "Volver a esta versión". */
export function DeploymentHistory({
  projectId,
  environments,
  canDeploy,
  onShowLogs,
  onStarted,
  onPublish,
}: {
  projectId: string;
  environments: Environment[];
  canDeploy: boolean;
  onShowLogs: (deployment: Deployment) => void;
  onStarted: (deployment: Deployment) => void;
  onPublish: () => void;
}) {
  const t = useTranslations("deployments.history");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const envLabel = useEnvironmentLabel();
  const memberName = useMemberName();
  const errorText = useApiErrorText();
  const qc = useQueryClient();
  const upgrade = useUpgradeDialog();

  const [filter, setFilter] = React.useState<EnvironmentName | typeof ALL>(ALL);
  const [target, setTarget] = React.useState<Deployment | null>(null);
  const history = useDeploymentHistory(projectId, filter === ALL ? undefined : filter);
  const busyEnvs = new Set((history.data ?? []).filter((d) => isActive(d.status)).map((d) => d.environment));

  const rollback = useMutation({
    mutationFn: (dep: Deployment) => http.post<Deployment>(`/deployments/${dep.id}/rollback`),
    onSuccess: (dep) => {
      setTarget(null);
      qc.setQueryData(deploymentKeys.detail(dep.id), dep);
      void qc.invalidateQueries({ queryKey: deploymentKeys.allHistory(projectId) });
      toast.success(t("rollbackStarted", { version: dep.version ?? "—", environment: envLabel(dep.environment) }));
      onStarted(dep);
    },
    onError: (err) => {
      setTarget(null);
      if (!upgrade.handle(err)) toast.error(errorText(err));
    },
  });

  const canRollback = (dep: Deployment): boolean => {
    if (!canDeploy || (dep.status !== "superseded" && dep.status !== "live")) return false;
    if (busyEnvs.has(dep.environment)) return false;
    const env = environments.find((e) => e.name === dep.environment);
    return Boolean(env) && env?.deployed_version_id !== dep.version_id;
  };

  const filterOptions = [
    { value: ALL, label: t("allEnvironments") },
    ...ENVIRONMENTS.map((name) => ({ value: name, label: envLabel(name) })),
  ];

  let body: React.ReactNode;
  if (history.isLoading) {
    body = (
      <div className="p-4">
        <SkeletonRows rows={4} />
      </div>
    );
  } else if (history.error) {
    body = (
      <div className="p-4">
        <ErrorState title={tc("errorTitle")} description={t("error")} onRetry={() => void history.refetch()} retryLabel={tc("retry")} />
      </div>
    );
  } else if (!history.data?.length) {
    body = (
      <div className="p-4">
        <EmptyState
          icon={<History />}
          title={filter === ALL ? t("empty.title") : t("empty.filteredTitle", { environment: envLabel(filter) })}
          description={t("empty.description")}
          action={
            canDeploy ? (
              <Button variant="primary" onClick={onPublish}>
                <Rocket />
                {t("empty.action")}
              </Button>
            ) : undefined
          }
        />
      </div>
    );
  } else {
    body = (
      <Table aria-label={t("title")}>
        <THead>
          <tr>
            <TH>{t("columns.version")}</TH>
            <TH>{t("columns.environment")}</TH>
            <TH className="hidden md:table-cell">{t("columns.commit")}</TH>
            <TH className="hidden lg:table-cell">{t("columns.who")}</TH>
            <TH>{t("columns.when")}</TH>
            <TH>{t("columns.status")}</TH>
            <TH className="text-right">
              <span className="sr-only">{tc("actions")}</span>
            </TH>
          </tr>
        </THead>
        <TBody>
          {history.data.map((dep) => (
            <TR key={dep.id}>
              <TD className="max-w-[16rem]">
                <p className="tabular font-semibold">{dep.version !== null ? `v${dep.version}` : "—"}</p>
                {dep.message ? <p className="truncate text-xs text-fg-muted">{dep.message}</p> : null}
              </TD>
              <TD className="whitespace-nowrap">{envLabel(dep.environment)}</TD>
              <TD className="hidden font-mono text-xs md:table-cell">{shortHash(dep.git_commit)}</TD>
              <TD className="hidden max-w-[12rem] truncate text-fg-muted lg:table-cell">{memberName(dep.created_by) ?? "—"}</TD>
              <TD className="whitespace-nowrap text-fg-muted">
                <time dateTime={dep.created_at} title={formatDate(dep.created_at, locale, true)}>
                  {formatRelative(dep.created_at, locale)}
                </time>
              </TD>
              <TD>
                <div className="flex flex-wrap items-center gap-1">
                  <DeploymentStatusBadge status={dep.status} />
                  {dep.forced ? <ForcedBadge /> : null}
                </div>
              </TD>
              <TD>
                <div className="flex justify-end gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => onShowLogs(dep)}
                    aria-label={t("logsFor", { version: dep.version ?? "—", environment: envLabel(dep.environment) })}
                  >
                    <ScrollText />
                    <span className="hidden sm:inline">{t("logs")}</span>
                  </Button>
                  {canRollback(dep) ? (
                    <Button size="sm" variant="secondary" onClick={() => setTarget(dep)}>
                      <Undo2 />
                      {t("rollback")}
                    </Button>
                  ) : null}
                </div>
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
    );
  }

  return (
    <Card>
      <CardHeader
        title={t("title")}
        description={t("description")}
        actions={
          <Select
            aria-label={t("filterLabel")}
            value={filter}
            onValueChange={(v) => setFilter(v as EnvironmentName | typeof ALL)}
            options={filterOptions}
            className="w-44"
          />
        }
      />
      {body}
      <ConfirmDialog
        open={target !== null}
        onOpenChange={(open) => {
          if (!open && !rollback.isPending) setTarget(null);
        }}
        title={t("rollbackTitle", {
          version: target?.version ?? "—",
          environment: target ? envLabel(target.environment) : "",
        })}
        description={t("rollbackDescription", { commit: shortHash(target?.git_commit) })}
        confirmLabel={t("rollback")}
        cancelLabel={tc("cancel")}
        loading={rollback.isPending}
        onConfirm={() => {
          if (target) rollback.mutate(target);
        }}
      />
      {upgrade.dialog}
    </Card>
  );
}
