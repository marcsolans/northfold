"use client";

import {
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  PageHeader,
  SkeletonRows,
  Stat,
  StatusDot,
} from "@messer/ui";
import { Activity, Bot, Plus, Server, Workflow } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { projectHref } from "@/components/shell/nav-config";
import { RunsTable } from "@/components/traces/runs-table";
import { formatNumber, formatRelative, localeTag } from "@/lib/format";
import { useRole } from "@/lib/hooks/use-me";
import { useEnvironments, useMembers, useProject, useRecentRuns } from "@/lib/studio/hooks";

import { ENABLED_PROJECT_TABS } from "./project-tabs";

export function ProjectOverview({ projectId }: { projectId: string }) {
  const t = useTranslations("projects.overview");
  const tt = useTranslations("studio.tiers");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const canBuild = useRole("builder");
  const project = useProject(projectId);
  const members = useMembers(projectId);
  const runs = useRecentRuns(projectId);
  const envs = useEnvironments(projectId);
  const workflowsEnabled = ENABLED_PROJECT_TABS.includes("workflows");

  const p = project.data;
  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-6 md:px-6">
      <PageHeader
        title={p?.name ?? "…"}
        description={p?.description || undefined}
        actions={
          canBuild ? (
            <Button asChild variant="primary">
              <Link href={`${projectHref(projectId, "agents")}?new=1`}>
                <Plus />
                {t("newAgent")}
              </Link>
            </Button>
          ) : null
        }
      />
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label={t("agents")} value={p ? formatNumber(p.agents, locale) : "—"} />
        <Stat label={t("workflows")} value={p ? formatNumber(p.workflows, locale) : "—"} />
        <Stat label={t("defaultTier")} value={p ? tt(`${p.default_model_tier}.label`) : "—"} />
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader
            title={t("recentRuns")}
            description={t("recentRunsHint")}
            actions={
              <Button asChild size="sm" variant="ghost">
                <Link href={projectHref(projectId, "traces")}>{t("allTraces")}</Link>
              </Button>
            }
          />
          {runs.isLoading ? (
            <div className="p-4">
              <SkeletonRows rows={4} />
            </div>
          ) : runs.error ? (
            <div className="p-4">
              <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void runs.refetch()} retryLabel={tc("retry")} />
            </div>
          ) : (runs.data?.items ?? []).length === 0 ? (
            <div className="p-4">
              <EmptyState icon={<Activity />} title={t("noRuns")} description={t("noRunsHint")} />
            </div>
          ) : (
            <RunsTable runs={runs.data?.items ?? []} compact />
          )}
        </Card>

        <div className="flex flex-col gap-4">
          <Card>
            <CardHeader title={t("workforce")} description={t("workforceHint")} />
            {members.isLoading ? (
              <div className="p-4">
                <SkeletonRows rows={3} />
              </div>
            ) : members.error ? (
              <div className="p-4">
                <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void members.refetch()} retryLabel={tc("retry")} />
              </div>
            ) : (members.data ?? []).length === 0 ? (
              <p className="px-4 py-6 text-center text-sm text-fg-subtle">{t("noMembers")}</p>
            ) : (
              <ul className="divide-y divide-border">
                {(members.data ?? []).map((m) => {
                  const Icon = m.kind === "agent" ? Bot : Workflow;
                  const href =
                    m.kind === "agent"
                      ? `${projectHref(projectId, "agents")}/${encodeURIComponent(m.name)}`
                      : workflowsEnabled
                        ? `${projectHref(projectId, "workflows")}/${encodeURIComponent(m.name)}`
                        : null;
                  const body = (
                    <>
                      <Icon className="size-4 shrink-0 text-fg-subtle" aria-hidden />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-mono text-xs font-medium">{m.name}</span>
                        <span className="block truncate text-xs text-fg-muted">{m.description || t(`kind.${m.kind}`)}</span>
                      </span>
                      <Badge tone="outline">v{m.current_version}</Badge>
                    </>
                  );
                  return (
                    <li key={m.id}>
                      {href ? (
                        <Link href={href} className="flex items-center gap-2.5 px-4 py-2.5 hover:bg-subtle">
                          {body}
                        </Link>
                      ) : (
                        <div className="flex items-center gap-2.5 px-4 py-2.5">{body}</div>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>

          <Card>
            <CardHeader title={t("environments")} />
            {envs.isLoading ? (
              <div className="p-4">
                <SkeletonRows rows={2} />
              </div>
            ) : envs.error ? (
              <div className="p-4">
                <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void envs.refetch()} retryLabel={tc("retry")} />
              </div>
            ) : (
              <ul className="divide-y divide-border">
                {(envs.data ?? []).map((env) => {
                  const deployed = Boolean(env.deployed_version_id);
                  const url = env.custom_domain ? `https://${env.custom_domain}` : env.url;
                  return (
                    <li key={env.id} className="flex items-start gap-2.5 px-4 py-2.5">
                      <Server className="mt-0.5 size-4 shrink-0 text-fg-subtle" aria-hidden />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium">{t.has(`env.${env.name}`) ? t(`env.${env.name}`) : env.name}</p>
                        {url ? (
                          <a href={url} target="_blank" rel="noopener noreferrer" className="block truncate text-xs text-accent hover:underline">
                            {url}
                          </a>
                        ) : (
                          <p className="text-xs text-fg-subtle">{deployed ? t("noUrl") : t("notDeployed")}</p>
                        )}
                      </div>
                      <Badge tone={deployed ? "success" : "outline"}>
                        <StatusDot tone={deployed ? "success" : "neutral"} />
                        {deployed ? t("deployed") : env.status || t("idle")}
                      </Badge>
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>
          {p ? (
            <p className="text-xs text-fg-subtle">
              {t("updated", { when: formatRelative(p.updated_at, locale) })}
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
