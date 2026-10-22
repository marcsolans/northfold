"use client";

import { Alert, Button, Dialog, DialogContent, Field, Input, RadioCards, Textarea, toast } from "@messer/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { ApiError, http } from "@/lib/api";
import { errorMessage, studioKeys } from "@/lib/studio/hooks";
import { MODEL_TIERS, type ModelTier, type Project } from "@/lib/studio/types";

export function CreateProjectDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const t = useTranslations("projects.create");
  const tt = useTranslations("studio.tiers");
  const tc = useTranslations("common");
  const router = useRouter();
  const qc = useQueryClient();
  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [tier, setTier] = React.useState<ModelTier>("standard");
  const [touched, setTouched] = React.useState(false);

  React.useEffect(() => {
    if (open) {
      setName("");
      setDescription("");
      setTier("standard");
      setTouched(false);
    }
  }, [open]);

  const create = useMutation({
    mutationFn: () =>
      http.post<Project>("/projects", { name: name.trim(), description: description.trim(), default_model_tier: tier }),
    onSuccess: (project) => {
      void qc.invalidateQueries({ queryKey: studioKeys.projects });
      toast.success(t("created", { name: project.name }));
      onOpenChange(false);
      router.push(`/app/projects/${project.id}`);
    },
  });

  const nameError = touched && !name.trim() ? t("nameRequired") : null;
  const planLimit = create.error instanceof ApiError && create.error.isPlanLimit;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (!name.trim()) return;
    create.mutate();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={t("title")} description={t("description")}>
        <form id="create-project" onSubmit={submit} className="flex flex-col gap-4" noValidate>
          <Field label={t("name")} htmlFor="project-name" error={nameError}>
            <Input
              id="project-name"
              value={name}
              maxLength={200}
              autoFocus
              aria-invalid={Boolean(nameError)}
              placeholder={t("namePlaceholder")}
              onChange={(e) => setName(e.target.value)}
              onBlur={() => setTouched(true)}
            />
          </Field>
          <Field label={t("descriptionLabel")} htmlFor="project-description" hint={tc("optional")}>
            <Textarea
              id="project-description"
              value={description}
              maxLength={2000}
              rows={3}
              placeholder={t("descriptionPlaceholder")}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
          <fieldset className="flex flex-col gap-1.5">
            <legend className="mb-1.5 text-sm font-medium">{t("tier")}</legend>
            <RadioCards
              value={tier}
              onValueChange={(v) => setTier(v as ModelTier)}
              className="grid-cols-1 sm:grid-cols-3"
              options={MODEL_TIERS.map((value) => ({ value, label: tt(`${value}.label`), description: tt(`${value}.description`) }))}
            />
          </fieldset>
          {create.error ? (
            <Alert
              tone={planLimit ? "warning" : "danger"}
              action={
                planLimit ? (
                  <Button asChild size="sm" variant="dark">
                    <Link href="/app/settings/billing">{tc("upgrade")}</Link>
                  </Button>
                ) : null
              }
            >
              {errorMessage(create.error, tc("errorGeneric"))}
            </Alert>
          ) : null}
        </form>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={() => onOpenChange(false)}>
            {tc("cancel")}
          </Button>
          <Button variant="primary" type="submit" form="create-project" loading={create.isPending}>
            {t("submit")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
