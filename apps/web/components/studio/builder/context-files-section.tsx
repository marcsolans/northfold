"use client";

import { Button, ConfirmDialog, toast } from "@messer/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileText, Trash2, Upload } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";
import { formatNumber, localeTag } from "@/lib/format";
import { errorMessage, studioKeys } from "@/lib/studio/hooks";
import type { ContextFile } from "@/lib/studio/types";

import { Section } from "./fields";

export const CONTEXT_FILE_ACCEPT = ".md,.txt,.csv,.json,.yaml,.yml,.xml,.tsv,.html,.pdf,.docx";
const CONTEXT_FILE_MAX = 5 * 1024 * 1024;

export function formatBytes(bytes: number, locale: string): string {
  if (bytes < 1024) return `${formatNumber(bytes, locale)} B`;
  if (bytes < 1024 * 1024) return `${formatNumber(bytes / 1024, locale, 1)} KB`;
  return `${formatNumber(bytes / (1024 * 1024), locale, 1)} MB`;
}

export function ContextFilesSection({
  projectId,
  member,
  files,
  readOnly,
  disabledReason,
}: {
  projectId: string;
  member: string;
  files: ContextFile[];
  readOnly: boolean;
  disabledReason: string | null;
}) {
  const t = useTranslations("studio.builder.contextFiles");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const inputRef = React.useRef<HTMLInputElement>(null);
  const [removing, setRemoving] = React.useState<string | null>(null);
  const base = `/projects/${projectId}/workforce/${encodeURIComponent(member)}/context-files`;

  const refresh = () => qc.invalidateQueries({ queryKey: studioKeys.member(projectId, member) });

  const upload = useMutation({
    mutationFn: async (list: File[]) => {
      for (const file of list) {
        const form = new FormData();
        form.append("file", file);
        await http.post<ContextFile>(base, form);
      }
    },
    onSuccess: (_, list) => {
      toast.success(t("uploaded", { count: list.length }));
      void refresh();
    },
    onError: (err) => {
      toast.error(errorMessage(err, tc("errorGeneric")));
      void refresh();
    },
  });

  const remove = useMutation({
    mutationFn: (name: string) => http.del(`${base}/${encodeURIComponent(name)}`),
    onSuccess: () => {
      setRemoving(null);
      void refresh();
    },
    onError: (err) => toast.error(errorMessage(err, tc("errorGeneric"))),
  });

  const pick = (fileList: FileList | null) => {
    const list = Array.from(fileList ?? []);
    if (inputRef.current) inputRef.current.value = "";
    const allowed = CONTEXT_FILE_ACCEPT.split(",");
    const bad = list.find((f) => !allowed.some((ext) => f.name.toLowerCase().endsWith(ext)));
    if (bad) {
      toast.error(t("unsupported", { name: bad.name }));
      return;
    }
    const big = list.find((f) => f.size > CONTEXT_FILE_MAX);
    if (big) {
      toast.error(t("tooLarge", { name: big.name }));
      return;
    }
    if (list.length) upload.mutate(list);
  };

  const locked = readOnly || disabledReason !== null;
  return (
    <Section
      id="context-files"
      title={t("title")}
      description={t("description")}
      actions={
        locked ? null : (
          <>
            <input
              ref={inputRef}
              type="file"
              multiple
              accept={CONTEXT_FILE_ACCEPT}
              className="sr-only"
              id="context-file-input"
              aria-label={t("upload")}
              onChange={(e) => pick(e.target.files)}
            />
            <Button size="sm" variant="secondary" loading={upload.isPending} onClick={() => inputRef.current?.click()}>
              <Upload />
              {t("upload")}
            </Button>
          </>
        )
      }
    >
      {disabledReason ? <p className="text-xs text-fg-subtle">{disabledReason}</p> : null}
      {files.length === 0 ? (
        <p className="text-sm text-fg-subtle">{t("empty")}</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {files.map((file) => (
            <li key={file.name} className="flex items-center gap-2.5 rounded-md border border-border px-3 py-2">
              <FileText className="size-4 shrink-0 text-fg-subtle" aria-hidden />
              <span className="min-w-0 flex-1 truncate text-sm">{file.name}</span>
              <span className="tabular text-xs text-fg-subtle">{formatBytes(file.size, locale)}</span>
              {locked ? null : (
                <Button size="icon-sm" variant="ghost" aria-label={t("remove", { name: file.name })} onClick={() => setRemoving(file.name)}>
                  <Trash2 />
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs text-fg-subtle">{t("formats")}</p>
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => {
          if (!open) setRemoving(null);
        }}
        title={t("removeTitle", { name: removing ?? "" })}
        description={t("removeDescription")}
        confirmLabel={tc("delete")}
        cancelLabel={tc("cancel")}
        loading={remove.isPending}
        onConfirm={() => {
          if (removing) remove.mutate(removing);
        }}
      />
    </Section>
  );
}
