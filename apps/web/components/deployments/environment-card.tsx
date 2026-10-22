"use client";

import { Badge, Button, Card, CardBody, CardFooter, CardHeader, CopyButton, Separator, StatusDot } from "@messer/ui";
import { ExternalLink, Rocket } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { formatDate, formatRelative, localeTag } from "@/lib/format";
import { shortHash } from "@/lib/studio/format";
import type { Environment, Version } from "@/lib/studio/types";

import { DomainPanel } from "./domain-panel";
import { DeploymentStatusBadge, useEnvironmentLabel } from "./labels";
import { useMemberName } from "./queries";
import { type Deployment, type EnvironmentName, isEnvironmentName } from "./types";

/** One environment: deployed version, commit, URL (copy/open), status, publish button and custom domain. */
export function EnvironmentCard({
  projectId,
  environment,
  versions,
  lastLive,
  active,
  canDeploy,
  canManageDomain,
  onPublish,
}: {
  projectId: string;
  environment: Environment;
  versions: Version[] | undefined;
  lastLive: Deployment | undefined;
  active: Deployment | undefined;
  canDeploy: boolean;
  canManageDomain: boolean;
  onPublish: (environment: EnvironmentName) => void;
}) {
  const t = useTranslations("deployments.environment");
  const te = useTranslations("deployments.environments");
  const locale = localeTag(useLocale());
  const envLabel = useEnvironmentLabel();
  const memberName = useMemberName();

  const deployedId = environment.deployed_version_id;
  const version = versions?.find((v) => v.id === deployedId);
  const fromDeployment = lastLive && lastLive.version_id === deployedId ? lastLive : undefined;
  const number = version?.version ?? fromDeployment?.version ?? null;
  const commit = version?.git_commit ?? fromDeployment?.git_commit ?? null;
  const message = version?.message ?? fromDeployment?.message ?? null;
  const publishedAt = fromDeployment?.finished_at ?? fromDeployment?.created_at ?? null;
  const who = memberName(fromDeployment?.created_by);
  const deployed = Boolean(deployedId);
  const url = deployed ? environment.url : null;
  const name = environment.name;

  return (
    <Card className="flex flex-col">
      <CardHeader
        title={envLabel(name)}
        description={te.has(`${name}.description`) ? te(`${name}.description`) : undefined}
        actions={
          active ? (
            <DeploymentStatusBadge status={active.status} />
          ) : deployed ? (
            <Badge tone="success">
              <StatusDot tone="success" />
              {t("live")}
            </Badge>
          ) : (
            <Badge tone="outline">
              <StatusDot tone="neutral" />
              {t("notDeployed")}
            </Badge>
          )
        }
      />
      <CardBody className="flex flex-1 flex-col gap-4">
        {deployed ? (
          <dl className="grid gap-3 text-sm sm:grid-cols-2">
            <div className="min-w-0">
              <dt className="text-xs text-fg-subtle">{t("version")}</dt>
              <dd className="truncate">
                <span className="tabular font-semibold">{number !== null ? `v${number}` : "—"}</span>
                {message ? <span className="text-fg-muted"> · {message}</span> : null}
              </dd>
            </div>
            <div className="min-w-0">
              <dt className="text-xs text-fg-subtle">{t("commit")}</dt>
              <dd className="flex items-center gap-1 font-mono text-xs">
                <span>{shortHash(commit)}</span>
                {commit ? <CopyButton value={commit} label={t("copyCommit")} /> : null}
              </dd>
            </div>
            <div className="min-w-0 sm:col-span-2">
              <dt className="text-xs text-fg-subtle">{t("published")}</dt>
              <dd>
                {publishedAt ? (
                  <time dateTime={publishedAt} title={formatDate(publishedAt, locale, true)}>
                    {formatRelative(publishedAt, locale)}
                  </time>
                ) : (
                  "—"
                )}
                {who ? <span className="text-fg-muted"> · {t("by", { name: who })}</span> : null}
              </dd>
            </div>
            <div className="min-w-0 sm:col-span-2">
              <dt className="text-xs text-fg-subtle">{t("url")}</dt>
              <dd className="flex min-w-0 items-center gap-1">
                {url ? (
                  <>
                    <a href={url} target="_blank" rel="noopener noreferrer" className="truncate text-accent hover:underline">
                      {url}
                    </a>
                    <CopyButton value={url} label={t("copyUrl")} />
                    <Button asChild variant="ghost" size="icon-sm">
                      <a href={url} target="_blank" rel="noopener noreferrer" aria-label={t("openUrl")}>
                        <ExternalLink />
                      </a>
                    </Button>
                  </>
                ) : (
                  <span className="text-fg-subtle">{t("noUrl")}</span>
                )}
              </dd>
            </div>
          </dl>
        ) : (
          <p className="text-sm text-fg-muted">{t("emptyHint", { environment: envLabel(name) })}</p>
        )}
        <Separator />
        <DomainPanel projectId={projectId} environment={environment} canManage={canManageDomain} />
      </CardBody>
      {canDeploy && isEnvironmentName(name) ? (
        <CardFooter>
          <Button variant={name === "production" ? "primary" : "secondary"} disabled={Boolean(active)} onClick={() => onPublish(name)}>
            <Rocket />
            {t("publish", { environment: envLabel(name) })}
          </Button>
        </CardFooter>
      ) : null}
    </Card>
  );
}
