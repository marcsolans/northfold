"use client";

import { Alert, Button, Dialog, DialogContent, Field, Input, Textarea, toast } from "@messer/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";
import { memberNameProblem } from "@/lib/studio/agent-config";
import { errorMessage, studioKeys } from "@/lib/studio/hooks";
import type { MemberDetail } from "@/lib/studio/types";

function suggestName(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[\s-]+/g, "_");
}

export function CreateAgentDialog({
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
  const t = useTranslations("studio.agents.create");
  const tc = useTranslations("common");
  const router = useRouter();
  const qc = useQueryClient();
  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [touched, setTouched] = React.useState(false);

  React.useEffect(() => {
    if (open) {
      setName("");
      setDescription("");
      setTouched(false);
    }
  }, [open]);

  const create = useMutation({
    mutationFn: () =>
      http.post<MemberDetail>(`/projects/${projectId}/workforce`, { name, description: description.trim() }),
    onSuccess: (member) => {
      void qc.invalidateQueries({ queryKey: ["projects", projectId] });
      void qc.invalidateQueries({ queryKey: studioKeys.projects, exact: true });
      qc.setQueryData(studioKeys.member(projectId, member.name), member);
      toast.success(t("created", { name: member.name }));
      onOpenChange(false);
      router.push(`/app/projects/${projectId}/agents/${encodeURIComponent(member.name)}`);
    },
  });

  const problem = memberNameProblem(name);
  const taken = existing.includes(name);
  const showError = (touched || name.length > 0) && (problem !== null || taken);
  const nameError = showError ? (taken ? t("errors.taken") : t(`errors.${problem ?? "chars"}`)) : null;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (problem || taken) return;
    create.mutate();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={t("title")} description={t("description")}>
        <form id="create-agent" onSubmit={submit} className="flex flex-col gap-4" noValidate>
          <Field label={t("name")} htmlFor="agent-name" error={nameError} hint={t("nameHint")}>
            <Input
              id="agent-name"
              value={name}
              maxLength={63}
              autoFocus
              autoComplete="off"
              spellCheck={false}
              className="font-mono"
              placeholder="soporte_facturas"
              aria-invalid={Boolean(nameError)}
              aria-describedby="agent-name-rule"
              onChange={(e) => setName(suggestName(e.target.value))}
              onBlur={() => setTouched(true)}
            />
          </Field>
          <p id="agent-name-rule" className="sr-only">
            {t("nameHint")}
          </p>
          <Field label={t("descriptionLabel")} htmlFor="agent-description" hint={tc("optional")}>
            <Textarea
              id="agent-description"
              value={description}
              rows={3}
              maxLength={2000}
              placeholder={t("descriptionPlaceholder")}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
          {create.error ? <Alert tone="danger">{errorMessage(create.error, tc("errorGeneric"))}</Alert> : null}
        </form>
        <div className="mt-5 flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
            {tc("cancel")}
          </Button>
          <Button type="submit" form="create-agent" variant="primary" loading={create.isPending} disabled={Boolean(nameError)}>
            {t("submit")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
