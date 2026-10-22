"use client";

import {
  Alert,
  Button,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  ConfirmDialog,
  CopyButton,
  ErrorState,
  Field,
  Input,
  PageHeader,
  RadioCards,
  SkeletonRows,
  Textarea,
  toast,
} from "@messer/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { ExportCard } from "@/components/projects/export-card";
import { GithubSettings } from "@/components/projects/github-settings";
import { http } from "@/lib/api";
import { formatDate, localeTag } from "@/lib/format";
import { useRole } from "@/lib/hooks/use-me";
import { errorMessage, studioKeys, useProject, useUnsavedChangesGuard } from "@/lib/studio/hooks";
import { MODEL_TIERS, type ModelTier, type Project } from "@/lib/studio/types";

export function ProjectSettings({ projectId }: { projectId: string }) {
  const t = useTranslations("projects.settings");
  const tt = useTranslations("studio.tiers");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const router = useRouter();
  const qc = useQueryClient();
  const canEdit = useRole("builder");
  const isAdmin = useRole("admin");
  const project = useProject(projectId);

  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [tier, setTier] = React.useState<ModelTier>("standard");
  const [archiveOpen, setArchiveOpen] = React.useState(false);
  const [confirmName, setConfirmName] = React.useState("");
  const [archiveTried, setArchiveTried] = React.useState(false);

  const p = project.data;
  React.useEffect(() => {
    if (!p) return;
    setName(p.name);
    setDescription(p.description);
    setTier(p.default_model_tier);
  }, [p]);

  const dirty = Boolean(p) && (name !== p?.name || description !== p?.description || tier !== p?.default_model_tier);
  const guard = useUnsavedChangesGuard(dirty);

  const save = useMutation({
    mutationFn: () =>
      http.patch<Project>(`/projects/${projectId}`, {
        name: name.trim(),
        description: description.trim(),
        default_model_tier: tier,
      }),
    onSuccess: (updated) => {
      qc.setQueryData(studioKeys.project(projectId), (prev: Project | undefined) => ({ ...(prev ?? updated), ...updated }));
      void qc.invalidateQueries({ queryKey: studioKeys.projects, exact: true });
      toast.success(t("saved"));
    },
    onError: (err) => toast.error(errorMessage(err, tc("errorGeneric"))),
  });

  const archive = useMutation({
    mutationFn: () => http.del(`/projects/${projectId}`),
    onSuccess: () => {
      setArchiveOpen(false);
      void qc.invalidateQueries({ queryKey: studioKeys.projects });
      toast.success(t("archived", { name: p?.name ?? "" }));
      router.push("/app/projects");
    },
    onError: (err) => toast.error(errorMessage(err, tc("errorGeneric"))),
  });

  if (project.isLoading) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-6 md:px-6">
        <SkeletonRows rows={6} />
      </div>
    );
  }
  if (project.error || !p) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-6 md:px-6">
        <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void project.refetch()} retryLabel={tc("retry")} />
      </div>
    );
  }

  const nameError = !name.trim() ? t("nameRequired") : null;

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-6 md:px-6">
      <PageHeader title={t("title")} description={t("description")} className="pb-0" />
      <Card>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!nameError && dirty) save.mutate();
          }}
        >
          <CardHeader title={t("general")} />
          <CardBody className="flex flex-col gap-4">
            {!canEdit ? <Alert tone="info">{t("readOnly")}</Alert> : null}
            <Field label={t("name")} htmlFor="ps-name" error={nameError}>
              <Input
                id="ps-name"
                value={name}
                maxLength={200}
                disabled={!canEdit}
                aria-invalid={Boolean(nameError)}
                onChange={(e) => setName(e.target.value)}
              />
            </Field>
            <Field label={t("descriptionLabel")} htmlFor="ps-description">
              <Textarea
                id="ps-description"
                value={description}
                maxLength={2000}
                rows={3}
                disabled={!canEdit}
                onChange={(e) => setDescription(e.target.value)}
              />
            </Field>
            <fieldset disabled={!canEdit}>
              <legend className="mb-1.5 text-sm font-medium">{t("tier")}</legend>
              <p className="mb-2 text-xs text-fg-subtle">{t("tierHint")}</p>
              <RadioCards
                value={tier}
                onValueChange={(v) => setTier(v as ModelTier)}
                className="grid-cols-1 sm:grid-cols-3"
                options={MODEL_TIERS.map((value) => ({
                  value,
                  label: tt(`${value}.label`),
                  description: tt(`${value}.description`),
                  disabled: !canEdit,
                }))}
              />
            </fieldset>
          </CardBody>
          {canEdit ? (
            <CardFooter>
              {dirty ? <span className="mr-auto text-xs text-warning">{t("unsaved")}</span> : null}
              <Button type="submit" variant="primary" disabled={!dirty || Boolean(nameError)} loading={save.isPending}>
                {tc("save")}
              </Button>
            </CardFooter>
          ) : null}
        </form>
      </Card>

      <Card>
        <CardHeader title={t("details")} />
        <CardBody>
          <dl className="grid gap-3 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-xs text-fg-subtle">{t("projectId")}</dt>
              <dd className="flex items-center gap-1 font-mono text-xs">
                <span className="truncate">{p.id}</span>
                <CopyButton value={p.id} label={tc("copy")} />
              </dd>
            </div>
            <div>
              <dt className="text-xs text-fg-subtle">{t("slug")}</dt>
              <dd className="font-mono text-xs">{p.slug}</dd>
            </div>
            <div>
              <dt className="text-xs text-fg-subtle">{tc("created")}</dt>
              <dd>{formatDate(p.created_at, locale, true)}</dd>
            </div>
            <div>
              <dt className="text-xs text-fg-subtle">{t("github")}</dt>
              <dd className="truncate">{p.github_repo ?? t("githubNone")}</dd>
            </div>
          </dl>
        </CardBody>
      </Card>

      <GithubSettings projectId={projectId} />
      <ExportCard projectId={projectId} />

      {isAdmin ? (
        <Card className="border-danger/30">
          <CardHeader title={t("archiveTitle")} description={t("archiveDescription")} />
          <CardFooter className="bg-transparent">
            <Button
              variant="danger"
              onClick={() => {
                setConfirmName("");
                setArchiveTried(false);
                setArchiveOpen(true);
              }}
            >
              {t("archive")}
            </Button>
          </CardFooter>
        </Card>
      ) : null}

      <ConfirmDialog
        open={archiveOpen}
        onOpenChange={setArchiveOpen}
        title={t("archiveConfirmTitle", { name: p.name })}
        description={t("archiveConfirmDescription")}
        confirmLabel={t("archive")}
        cancelLabel={tc("cancel")}
        loading={archive.isPending}
        onConfirm={() => {
          setArchiveTried(true);
          if (confirmName.trim() === p.name) archive.mutate();
        }}
      >
        <Field
          label={t("archiveConfirmLabel", { name: p.name })}
          htmlFor="archive-confirm"
          error={archiveTried && confirmName.trim() !== p.name ? t("archiveConfirmMismatch") : null}
        >
          <Input id="archive-confirm" value={confirmName} onChange={(e) => setConfirmName(e.target.value)} autoComplete="off" />
        </Field>
      </ConfirmDialog>

      <ConfirmDialog
        open={guard.pendingHref !== null}
        onOpenChange={(open) => {
          if (!open) guard.clear();
        }}
        title={t("leaveTitle")}
        description={t("leaveDescription")}
        confirmLabel={t("leave")}
        cancelLabel={tc("cancel")}
        onConfirm={() => {
          const href = guard.pendingHref;
          guard.clear();
          if (href) router.push(href);
        }}
      />
    </div>
  );
}
