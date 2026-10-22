"use client";

import { Button, Dialog, DialogContent, Field, Input, RadioCards, Textarea, toast } from "@messer/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";
import { errorMessage, studioKeys } from "@/lib/studio/hooks";
import { slugId } from "@/lib/workflows/graph";
import { workflowKeys, workflowPath } from "@/lib/workflows/hooks";
import type { StarterTemplate, WorkflowDetail } from "@/lib/workflows/types";

const NAME = /^[a-z][a-z0-9_]{0,62}$/;
const TEMPLATES: StarterTemplate[] = ["blank", "approval", "classify"];

export function CreateWorkflowDialog({
  projectId,
  open,
  onOpenChange,
  existing,
}: {
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  existing: string[];
}) {
  const t = useTranslations("workflows.create");
  const tc = useTranslations("common");
  const router = useRouter();
  const qc = useQueryClient();
  const [name, setName] = React.useState("");
  const [touched, setTouched] = React.useState(false);
  const [description, setDescription] = React.useState("");
  const [template, setTemplate] = React.useState<StarterTemplate>("blank");

  React.useEffect(() => {
    if (!open) {
      setName("");
      setTouched(false);
      setDescription("");
      setTemplate("blank");
    }
  }, [open]);

  const taken = existing.includes(name);
  const invalid = !NAME.test(name);
  const create = useMutation({
    mutationFn: () => http.post<WorkflowDetail>(workflowPath(projectId), { name, description: description.trim(), template }),
    onSuccess: (detail) => {
      toast.success(t("created", { name: detail.name }));
      void qc.invalidateQueries({ queryKey: workflowKeys.list(projectId) });
      void qc.invalidateQueries({ queryKey: studioKeys.project(projectId) });
      qc.setQueryData(workflowKeys.detail(projectId, detail.name), detail);
      onOpenChange(false);
      router.push(`/app/projects/${projectId}/workflows/${encodeURIComponent(detail.name)}`);
    },
    onError: (err) => toast.error(errorMessage(err, tc("errorGeneric"))),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        wide
        title={t("title")}
        description={t("description")}
        footer={
          <>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              {tc("cancel")}
            </Button>
            <Button variant="primary" loading={create.isPending} disabled={invalid || taken} onClick={() => create.mutate()}>
              {t("submit")}
            </Button>
          </>
        }
      >
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (!invalid && !taken) create.mutate();
          }}
        >
          <Field
            label={t("name")}
            htmlFor="workflow-name"
            hint={t("nameHint")}
            error={touched && invalid ? t("nameInvalid") : taken ? t("nameTaken") : undefined}
          >
            <Input
              id="workflow-name"
              value={name}
              className="font-mono"
              autoFocus
              onChange={(e) => setName(e.target.value.toLowerCase().replace(/[\s-]+/g, "_"))}
              onBlur={() => {
                setTouched(true);
                if (name && !NAME.test(name)) setName(slugId(name));
              }}
            />
          </Field>
          <Field label={t("descriptionLabel")} htmlFor="workflow-description-new">
            <Textarea id="workflow-description-new" rows={2} value={description} maxLength={2000} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          <Field label={t("template")}>
            <RadioCards
              value={template}
              onValueChange={(v) => setTemplate(v as StarterTemplate)}
              className="sm:grid-cols-3"
              options={TEMPLATES.map((key) => ({ value: key, label: t(`templates.${key}.label`), description: t(`templates.${key}.description`) }))}
            />
          </Field>
        </form>
      </DialogContent>
    </Dialog>
  );
}
