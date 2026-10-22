"use client";

import { Alert, Button, Checkbox, Dialog, DialogContent, Field, Input, Label, RadioCards, Select, Skeleton } from "@messer/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Rocket } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { isPlanLimitError, useUpgradeDialog } from "@/components/billing";
import { http } from "@/lib/api";
import { formatDate, localeTag } from "@/lib/format";
import { useRole } from "@/lib/hooks/use-me";
import { shortHash } from "@/lib/studio/format";
import type { Environment } from "@/lib/studio/types";

import { useEnvironmentLabel } from "./labels";
import { deploymentKeys, useApiErrorText, useProjectVersions } from "./queries";
import { type Deployment, ENVIRONMENTS, type EnvironmentName } from "./types";

const LATEST = "__latest__";

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/**
 * "Publicar": pick the environment and the version (or a new snapshot of the latest code), with an optional message.
 * Admins may force the deployment through a failing evals gate (audited); other roles never see that option.
 */
export function PublishDialog({
  projectId,
  open,
  onOpenChange,
  defaultEnvironment,
  environments,
  onStarted,
}: {
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaultEnvironment: EnvironmentName;
  environments: Environment[];
  onStarted: (deployment: Deployment) => void;
}) {
  const t = useTranslations("deployments.publish");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const envLabel = useEnvironmentLabel();
  const errorText = useApiErrorText();
  const qc = useQueryClient();
  const isAdmin = useRole("admin");
  const upgrade = useUpgradeDialog();
  const versions = useProjectVersions(projectId, open);

  const [environment, setEnvironment] = React.useState<EnvironmentName>(defaultEnvironment);
  const [versionId, setVersionId] = React.useState<string>(LATEST);
  const [message, setMessage] = React.useState("");
  const [force, setForce] = React.useState(false);

  const deploy = useMutation({
    mutationFn: () =>
      http.post<Deployment>(`/projects/${projectId}/deployments`, {
        environment,
        version_id: versionId === LATEST ? null : versionId,
        force: isAdmin && force,
        message: versionId === LATEST ? message.trim() : "",
      }),
    onSuccess: (dep) => {
      qc.setQueryData(deploymentKeys.detail(dep.id), dep);
      void qc.invalidateQueries({ queryKey: deploymentKeys.allHistory(projectId) });
      void qc.invalidateQueries({ queryKey: deploymentKeys.versions(projectId) });
      onOpenChange(false);
      onStarted(dep);
    },
    onError: (err) => {
      if (upgrade.handle(err)) onOpenChange(false);
    },
  });

  const { reset } = deploy;
  React.useEffect(() => {
    if (!open) return;
    setEnvironment(defaultEnvironment);
    setVersionId(LATEST);
    setMessage("");
    setForce(false);
    reset();
  }, [open, defaultEnvironment, reset]);

  const deployedIn = (id: string): string[] =>
    environments.filter((e) => e.deployed_version_id === id).map((e) => envLabel(e.name));

  const versionOptions = [
    { value: LATEST, label: t("latest"), description: t("latestHint") },
    ...(versions.data ?? []).map((v) => {
      const where = deployedIn(v.id);
      return {
        value: v.id,
        label: `v${v.version} · ${shortHash(v.git_commit)}${v.message ? ` · ${truncate(v.message, 50)}` : ""}`,
        description: [formatDate(v.created_at, locale, true), where.length ? t("deployedIn", { environments: where.join(", ") }) : null]
          .filter(Boolean)
          .join(" · "),
      };
    }),
  ];

  const apiError = deploy.error && !isPlanLimitError(deploy.error) ? deploy.error : null;

  return (
    <>
      <Dialog open={open} onOpenChange={(o) => !deploy.isPending && onOpenChange(o)}>
        <DialogContent
          title={t("title")}
          description={t("description")}
          footer={
            <>
              <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={deploy.isPending}>
                {tc("cancel")}
              </Button>
              <Button variant="primary" type="submit" form="publish-form" loading={deploy.isPending}>
                <Rocket />
                {t("submit", { environment: envLabel(environment) })}
              </Button>
            </>
          }
        >
          <form
            id="publish-form"
            className="flex flex-col gap-5"
            onSubmit={(e) => {
              e.preventDefault();
              deploy.mutate();
            }}
          >
            <fieldset className="flex flex-col gap-1.5">
              <legend className="mb-1.5 text-sm font-medium">{t("environment")}</legend>
              <RadioCards
                value={environment}
                onValueChange={(v) => setEnvironment(v as EnvironmentName)}
                className="grid-cols-1 sm:grid-cols-2"
                options={ENVIRONMENTS.map((name) => ({
                  value: name,
                  label: envLabel(name),
                  description: t(`environmentHint.${name}`),
                }))}
              />
            </fieldset>

            <Field label={t("version")} htmlFor="publish-version" hint={t("versionHint")}>
              {versions.isLoading ? (
                <Skeleton className="h-8 w-full" />
              ) : (
                <Select id="publish-version" value={versionId} onValueChange={setVersionId} options={versionOptions} />
              )}
            </Field>
            {versions.error ? <Alert tone="warning">{t("versionsError")}</Alert> : null}

            {versionId === LATEST ? (
              <Field label={t("message")} htmlFor="publish-message" hint={t("messageHint")}>
                <Input
                  id="publish-message"
                  value={message}
                  maxLength={500}
                  placeholder={t("messagePlaceholder")}
                  onChange={(e) => setMessage(e.target.value)}
                />
              </Field>
            ) : null}

            <Alert tone="info">{t("gateExplanation")}</Alert>

            {isAdmin ? (
              <div className="flex flex-col gap-2 rounded-md border border-border p-3">
                <div className="flex items-start gap-2">
                  <Checkbox id="publish-force" checked={force} onCheckedChange={(v) => setForce(v === true)} className="mt-0.5" />
                  <div className="flex flex-col gap-0.5">
                    <Label htmlFor="publish-force">{t("force")}</Label>
                    <p className="text-xs text-fg-muted">{t("forceHint")}</p>
                  </div>
                </div>
                {force ? <Alert tone="warning">{t("forceWarning")}</Alert> : null}
              </div>
            ) : null}

            {apiError ? <Alert tone="danger">{errorText(apiError)}</Alert> : null}
          </form>
        </DialogContent>
      </Dialog>
      {upgrade.dialog}
    </>
  );
}
