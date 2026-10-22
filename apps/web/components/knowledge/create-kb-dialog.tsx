"use client";

import { Alert, Button, Dialog, DialogContent, Field, Input, Select, Textarea, toast } from "@messer/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";

import { errorMessage, kbKeys, useEmbeddingModels } from "./queries";
import type { KnowledgeBase } from "./types";

export function CreateKnowledgeBaseDialog({
  open,
  onOpenChange,
  projectId,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId?: string | null;
  onCreated?: (kb: KnowledgeBase) => void;
}) {
  const t = useTranslations("knowledge.create");
  const tm = useTranslations("knowledge.models");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const models = useEmbeddingModels(open);
  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [model, setModel] = React.useState<string>("");
  const [advanced, setAdvanced] = React.useState(false);
  const [chunkSize, setChunkSize] = React.useState(800);
  const [overlap, setOverlap] = React.useState(120);
  const [error, setError] = React.useState<string | null>(null);

  const defaultModel = models.data?.find((m) => m.default)?.id ?? "";
  const selectedModel = model || defaultModel;

  const create = useMutation({
    mutationFn: () =>
      http.post<KnowledgeBase>("/knowledge-bases", {
        name: name.trim(),
        description: description.trim(),
        embedding_model: selectedModel || null,
        project_id: projectId ?? null,
        chunk_size_tokens: chunkSize,
        chunk_overlap_tokens: overlap,
      }),
    onSuccess: (kb) => {
      toast.success(t("created", { name: kb.name }));
      void qc.invalidateQueries({ queryKey: kbKeys.all });
      onOpenChange(false);
      setName("");
      setDescription("");
      setModel("");
      onCreated?.(kb);
    },
    onError: (err) => setError(errorMessage(err)),
  });

  const options = (models.data ?? []).map((m) => ({
    value: m.id,
    disabled: !m.available,
    label: `${m.id} · ${m.dim}`,
    description: m.available ? tm(m.kind as "local") : `${tm(m.kind as "local")} — ${t("unavailable")}`,
  }));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={t("title")} description={t("description")}>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            setError(null);
            create.mutate();
          }}
        >
          {error ? <Alert tone="danger">{error}</Alert> : null}
          <Field label={t("name")} htmlFor="kb-name">
            <Input
              id="kb-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("namePlaceholder")}
              maxLength={200}
              required
              autoFocus
            />
          </Field>
          <Field label={t("descriptionLabel")} htmlFor="kb-description" hint={tc("optional")}>
            <Textarea
              id="kb-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={2000}
              rows={3}
            />
          </Field>
          <Field label={t("model")} hint={t("modelHint")}>
            <Select
              aria-label={t("model")}
              value={selectedModel}
              onValueChange={setModel}
              options={options}
              disabled={models.isLoading}
              placeholder={models.isLoading ? tc("loading") : undefined}
            />
          </Field>
          <button
            type="button"
            className="self-start text-xs font-medium text-fg-muted underline-offset-4 hover:underline"
            onClick={() => setAdvanced((v) => !v)}
            aria-expanded={advanced}
          >
            {t("advanced")}
          </button>
          {advanced ? (
            <div className="grid grid-cols-2 gap-3">
              <Field label={t("chunkSize")} htmlFor="kb-chunk-size" hint={t("tokens")}>
                <Input
                  id="kb-chunk-size"
                  type="number"
                  min={100}
                  max={4000}
                  value={chunkSize}
                  onChange={(e) => setChunkSize(Number(e.target.value))}
                />
              </Field>
              <Field label={t("chunkOverlap")} htmlFor="kb-chunk-overlap" hint={t("tokens")}>
                <Input
                  id="kb-chunk-overlap"
                  type="number"
                  min={0}
                  max={1000}
                  value={overlap}
                  onChange={(e) => setOverlap(Number(e.target.value))}
                />
              </Field>
            </div>
          ) : null}
          <div className="mt-2 flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
              {tc("cancel")}
            </Button>
            <Button type="submit" variant="primary" loading={create.isPending} disabled={!name.trim()}>
              {t("submit")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
