"use client";

import { Alert, Button, Dialog, DialogContent, Field, Input, Textarea, toast } from "@messer/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";

import { errorMessage, kbKeys } from "./queries";
import type { KnowledgeBase } from "./types";

export function KbSettingsDialog({
  kb,
  open,
  onOpenChange,
}: {
  kb: KnowledgeBase;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("knowledge.settings");
  const tcreate = useTranslations("knowledge.create");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const [form, setForm] = React.useState({
    name: kb.name,
    description: kb.description,
    chunkSize: kb.chunk_size_tokens,
    overlap: kb.chunk_overlap_tokens,
  });
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (open) {
      setForm({ name: kb.name, description: kb.description, chunkSize: kb.chunk_size_tokens, overlap: kb.chunk_overlap_tokens });
      setError(null);
    }
  }, [open, kb]);

  const save = useMutation({
    mutationFn: () =>
      http.patch<KnowledgeBase>(`/knowledge-bases/${kb.id}`, {
        name: form.name.trim(),
        description: form.description.trim(),
        chunk_size_tokens: form.chunkSize,
        chunk_overlap_tokens: form.overlap,
      }),
    onSuccess: (updated) => {
      qc.setQueryData(kbKeys.detail(kb.id), updated);
      void qc.invalidateQueries({ queryKey: kbKeys.all });
      toast.success(tc("saved"));
      onOpenChange(false);
    },
    onError: (err) => setError(errorMessage(err)),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={t("title")} description={t("description")}>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            setError(null);
            save.mutate();
          }}
        >
          {error ? <Alert tone="danger">{error}</Alert> : null}
          <Field label={tcreate("name")} htmlFor="kb-settings-name">
            <Input
              id="kb-settings-name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              maxLength={200}
              required
            />
          </Field>
          <Field label={tcreate("descriptionLabel")} htmlFor="kb-settings-description">
            <Textarea
              id="kb-settings-description"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              maxLength={2000}
              rows={3}
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={tcreate("chunkSize")} htmlFor="kb-settings-size" hint={tcreate("tokens")}>
              <Input
                id="kb-settings-size"
                type="number"
                min={100}
                max={4000}
                value={form.chunkSize}
                onChange={(e) => setForm({ ...form, chunkSize: Number(e.target.value) })}
              />
            </Field>
            <Field label={tcreate("chunkOverlap")} htmlFor="kb-settings-overlap" hint={tcreate("tokens")}>
              <Input
                id="kb-settings-overlap"
                type="number"
                min={0}
                max={1000}
                value={form.overlap}
                onChange={(e) => setForm({ ...form, overlap: Number(e.target.value) })}
              />
            </Field>
          </div>
          <p className="text-xs text-fg-subtle">{t("chunkingHint")}</p>
          <dl className="grid grid-cols-[8rem_minmax(0,1fr)] gap-y-1 rounded-md border border-border bg-subtle p-3 text-xs">
            <dt className="text-fg-subtle">{t("model")}</dt>
            <dd className="font-mono">
              {kb.embedding_model} · {kb.embedding_dim}
            </dd>
            <dt className="text-fg-subtle">{t("schema")}</dt>
            <dd className="truncate font-mono">{kb.schema_name}</dd>
          </dl>
          <div className="mt-2 flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
              {tc("cancel")}
            </Button>
            <Button type="submit" variant="primary" loading={save.isPending} disabled={!form.name.trim()}>
              {tc("save")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
