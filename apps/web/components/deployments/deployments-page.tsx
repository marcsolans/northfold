"use client";

import { Alert, Button, Card, CardBody, EmptyState, ErrorState, PageHeader, Sheet, Skeleton } from "@messer/ui";
import { Rocket, Server } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { useMe } from "@/lib/hooks/use-me";
import { useEnvironments } from "@/lib/studio/hooks";
import type { Environment } from "@/lib/studio/types";
import { hasRole } from "@/lib/types";

import { DeploymentHistory } from "./deployment-history";
import { DeploymentProgress } from "./deployment-progress";
import { EnvironmentCard } from "./environment-card";
import { useEnvironmentLabel } from "./labels";
import { PublishDialog } from "./publish-dialog";
import { useDeploymentHistory, useProjectVersions } from "./queries";
import { type Deployment, ENVIRONMENTS, type EnvironmentName, isActive } from "./types";

function sortEnvironments(envs: Environment[]): Environment[] {
  const rank = (name: string) => {
    const i = ENVIRONMENTS.indexOf(name as EnvironmentName);
    return i === -1 ? ENVIRONMENTS.length : i;
  };
  return [...envs].sort((a, b) => rank(a.name) - rank(b.name) || a.name.localeCompare(b.name));
}

/** Project "Despliegues" tab: environments, publish, live progress, history with roll back and custom domains. */
export function DeploymentsPage({ projectId }: { projectId: string }) {
  const t = useTranslations("deployments");
  const tc = useTranslations("common");
  const envLabel = useEnvironmentLabel();
  const { data: me } = useMe();
  const canDeploy = hasRole(me, "builder");
  const isAdmin = hasRole(me, "admin");

  const envs = useEnvironments(projectId);
  const versions = useProjectVersions(projectId);
  const history = useDeploymentHistory(projectId);

  const [publishEnv, setPublishEnv] = React.useState<EnvironmentName | null>(null);
  const [lastPublishEnv, setLastPublishEnv] = React.useState<EnvironmentName>("production");
  const [pinned, setPinned] = React.useState<Deployment[]>([]);
  const [dismissed, setDismissed] = React.useState<ReadonlySet<string>>(() => new Set());
  const [logsOf, setLogsOf] = React.useState<Deployment | null>(null);

  const pin = React.useCallback((deps: Deployment[]) => {
    if (deps.length === 0) return;
    setPinned((prev) => {
      const known = new Set(prev.map((d) => d.id));
      const added = deps.filter((d) => !known.has(d.id));
      return added.length ? [...added, ...prev] : prev;
    });
  }, []);

  // Deployments in flight (started here or by someone else) get a live progress panel until dismissed.
  React.useEffect(() => {
    pin((history.data ?? []).filter((d) => isActive(d.status)));
  }, [history.data, pin]);

  const environments = sortEnvironments(envs.data ?? []);
  const deployments = history.data ?? [];
  const lastLive = (name: string) => deployments.find((d) => d.environment === name && d.status === "live");
  const activeIn = (name: string) => deployments.find((d) => d.environment === name && isActive(d.status));
  // One progress panel per environment: its most recent deployment followed in this session.
  const panels = [...pinned]
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .filter((d, i, all) => all.findIndex((x) => x.environment === d.environment) === i)
    .filter((d) => !dismissed.has(d.id));

  const openPublish = (env: EnvironmentName) => {
    setLastPublishEnv(env);
    setPublishEnv(env);
  };

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-6 md:px-6">
      <PageHeader
        title={t("title")}
        description={t("description")}
        className="pb-0"
        actions={
          canDeploy ? (
            <Button variant="primary" onClick={() => openPublish("production")}>
              <Rocket />
              {t("publishButton")}
            </Button>
          ) : null
        }
      />
      {me && !canDeploy ? <Alert tone="info">{t("readOnly")}</Alert> : null}

      {panels.map((dep) => (
        <section key={dep.id} aria-label={t("progress.regionLabel", { environment: envLabel(dep.environment) })}>
          <Card>
            <CardBody>
              <DeploymentProgress
                projectId={projectId}
                deployment={dep}
                notify
                onDismiss={() => setDismissed((prev) => new Set(prev).add(dep.id))}
              />
            </CardBody>
          </Card>
        </section>
      ))}

      <section aria-label={t("environmentsLabel")}>
        {envs.isLoading ? (
          <div className="grid gap-4 md:grid-cols-2">
            <Skeleton className="h-72 w-full" />
            <Skeleton className="h-72 w-full" />
          </div>
        ) : envs.error ? (
          <ErrorState title={tc("errorTitle")} description={t("environmentsError")} onRetry={() => void envs.refetch()} retryLabel={tc("retry")} />
        ) : environments.length === 0 ? (
          <EmptyState icon={<Server />} title={t("noEnvironments.title")} description={t("noEnvironments.description")} />
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {environments.map((env) => (
              <EnvironmentCard
                key={env.id}
                projectId={projectId}
                environment={env}
                versions={versions.data}
                lastLive={lastLive(env.name)}
                active={activeIn(env.name)}
                canDeploy={canDeploy}
                canManageDomain={isAdmin}
                onPublish={openPublish}
              />
            ))}
          </div>
        )}
      </section>

      <DeploymentHistory
        projectId={projectId}
        environments={environments}
        canDeploy={canDeploy}
        onShowLogs={setLogsOf}
        onStarted={(dep) => pin([dep])}
        onPublish={() => openPublish("production")}
      />

      <Sheet
        open={logsOf !== null}
        onOpenChange={(open) => {
          if (!open) setLogsOf(null);
        }}
        title={
          logsOf ? t("logsTitle", { version: logsOf.version ?? "—", environment: envLabel(logsOf.environment) }) : t("title")
        }
        description={t("logsDescription")}
        className="max-w-2xl"
      >
        {logsOf ? <DeploymentProgress key={logsOf.id} projectId={projectId} deployment={logsOf} /> : null}
      </Sheet>

      {canDeploy ? (
        <PublishDialog
          projectId={projectId}
          open={publishEnv !== null}
          onOpenChange={(open) => {
            if (!open) setPublishEnv(null);
          }}
          defaultEnvironment={publishEnv ?? lastPublishEnv}
          environments={environments}
          onStarted={(dep) => pin([dep])}
        />
      ) : null}
    </div>
  );
}
