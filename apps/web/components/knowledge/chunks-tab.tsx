"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Select,
  Sheet,
  SkeletonRows,
  Textarea,
  toast,
} from "@messer/ui";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Layers, Pencil, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";

import { errorMessage, kbKeys } from "./queries";
import type { ChunkList, FileList, KbChunk, KnowledgeBase } from "./types";

const PAGE = 25;

export function ChunksTab({ kb, canWrite }: { kb: KnowledgeBase; canWrite: boolean }) {
  const t = useTranslations("knowledge.chunks");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const [fileId, setFileId] = React.useState<string>("all");
  const [query, setQuery] = React.useState("");
  const [debounced, setDebounced] = React.useState("");
  const [offset, setOffset] = React.useState(0);
  const [editing, setEditing] = React.useState<KbChunk | null>(null);
  const [draft, setDraft] = React.useState({ content: "", heading: "" });
  const [deleting, setDeleting] = React.useState<KbChunk | null>(null);

  React.useEffect(() => {
    const id = window.setTimeout(() => {
      setDebounced(query.trim());
      setOffset(0);
    }, 300);
    return () => window.clearTimeout(id);
  }, [query]);

  const files = useQuery({
    queryKey: [...kbKeys.files(kb.id), "ready-options"],
    queryFn: () => http.get<FileList>(`/knowledge-bases/${kb.id}/files`, { status: "ready", limit: 500 }),
  });
  const chunks = useQuery({
    queryKey: [...kbKeys.chunks(kb.id), fileId, debounced, offset],
    queryFn: () =>
      http.get<ChunkList>(`/knowledge-bases/${kb.id}/chunks`, {
        file_id: fileId === "all" ? undefined : fileId,
        q: debounced || undefined,
        limit: PAGE,
        offset,
      }),
    placeholderData: keepPreviousData,
  });

  const save = useMutation({
    mutationFn: (chunk: KbChunk) =>
      http.patch<KbChunk>(`/knowledge-bases/${kb.id}/chunks/${chunk.id}`, {
        content: draft.content,
        heading: draft.heading.trim() || null,
      }),
    onSuccess: () => {
      toast.success(t("saved"));
      setEditing(null);
      void qc.invalidateQueries({ queryKey: kbKeys.chunks(kb.id) });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });
  const remove = useMutation({
    mutationFn: (chunk: KbChunk) => http.del(`/knowledge-bases/${kb.id}/chunks/${chunk.id}`),
    onSuccess: () => {
      toast.success(t("deleted"));
      setDeleting(null);
      void qc.invalidateQueries({ queryKey: kbKeys.chunks(kb.id) });
      void qc.invalidateQueries({ queryKey: kbKeys.files(kb.id) });
      void qc.invalidateQueries({ queryKey: kbKeys.detail(kb.id), exact: true });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const fileOptions = [
    { value: "all", label: t("allFiles") },
    ...(files.data?.items ?? []).filter((f) => f.chunk_count > 0).map((f) => ({ value: f.id, label: f.filename })),
  ];
  const items = chunks.data?.items ?? [];
  const total = chunks.data?.total ?? 0;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Select
          aria-label={t("file")}
          className="w-64"
          value={fileId}
          onValueChange={(v) => {
            setFileId(v);
            setOffset(0);
          }}
          options={fileOptions}
        />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("searchPlaceholder")}
          aria-label={t("searchPlaceholder")}
          className="max-w-xs"
        />
      </div>
      {chunks.isLoading ? (
        <SkeletonRows rows={5} />
      ) : chunks.error ? (
        <ErrorState title={tc("errorTitle")} description={errorMessage(chunks.error)} onRetry={() => void chunks.refetch()} retryLabel={tc("retry")} />
      ) : items.length === 0 ? (
        <EmptyState icon={<Layers />} title={debounced || fileId !== "all" ? t("noMatches") : t("empty")} description={t("emptyHint")} />
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map((chunk) => {
            const pages =
              chunk.page_from === null
                ? null
                : chunk.page_to === null || chunk.page_to === chunk.page_from
                  ? t("page", { page: chunk.page_from })
                  : t("pages", { from: chunk.page_from, to: chunk.page_to });
            return (
              <li key={chunk.id}>
                <Card className="flex flex-col gap-2 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-fg-muted">
                    <span className="flex min-w-0 flex-wrap items-center gap-2">
                      <span className="truncate font-medium text-fg">{chunk.filename}</span>
                      <span className="tabular">#{chunk.ordinal + 1}</span>
                      {pages ? <span>{pages}</span> : null}
                      <span className="tabular">{t("tokens", { count: chunk.token_count })}</span>
                      {chunk.metadata.reembed_pending ? <Badge tone="warning">{t("reembedPending")}</Badge> : null}
                      {chunk.edited_at ? <Badge tone="info">{t("edited")}</Badge> : null}
                      {!chunk.has_embedding ? <Badge tone="danger">{t("noEmbedding")}</Badge> : null}
                    </span>
                    {canWrite ? (
                      <span className="flex gap-1">
                        <Button
                          size="icon-sm"
                          variant="ghost"
                          aria-label={tc("edit")}
                          onClick={() => {
                            setDraft({ content: chunk.content, heading: chunk.heading ?? "" });
                            setEditing(chunk);
                          }}
                        >
                          <Pencil />
                        </Button>
                        <Button size="icon-sm" variant="ghost" aria-label={tc("delete")} onClick={() => setDeleting(chunk)}>
                          <Trash2 />
                        </Button>
                      </span>
                    ) : null}
                  </div>
                  {chunk.heading ? <p className="text-xs font-semibold text-fg-muted">{chunk.heading}</p> : null}
                  <p className="line-clamp-5 whitespace-pre-line text-sm leading-relaxed">{chunk.content}</p>
                </Card>
              </li>
            );
          })}
        </ul>
      )}
      {total > PAGE ? (
        <div className="flex items-center justify-between text-xs text-fg-muted">
          <span className="tabular">{t("range", { from: offset + 1, to: Math.min(offset + PAGE, total), total })}</span>
          <span className="flex gap-1">
            <Button size="sm" variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
              {t("previous")}
            </Button>
            <Button size="sm" variant="secondary" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>
              {t("next")}
            </Button>
          </span>
        </div>
      ) : null}

      <Sheet
        open={editing !== null}
        onOpenChange={(open) => !open && setEditing(null)}
        title={t("editTitle")}
        description={editing ? `${editing.filename} · #${editing.ordinal + 1}` : undefined}
        footer={
          <>
            <Button variant="secondary" onClick={() => setEditing(null)}>
              {tc("cancel")}
            </Button>
            <Button variant="primary" loading={save.isPending} disabled={!draft.content.trim()} onClick={() => editing && save.mutate(editing)}>
              {tc("save")}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <Alert tone="info">{t("reembedHint")}</Alert>
          <Field label={t("heading")} htmlFor="chunk-heading">
            <Input id="chunk-heading" value={draft.heading} onChange={(e) => setDraft((d) => ({ ...d, heading: e.target.value }))} maxLength={1000} />
          </Field>
          <Field label={t("content")} htmlFor="chunk-content">
            <Textarea
              id="chunk-content"
              value={draft.content}
              onChange={(e) => setDraft((d) => ({ ...d, content: e.target.value }))}
              rows={18}
              maxLength={50000}
              className="font-mono text-xs"
            />
          </Field>
        </div>
      </Sheet>
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={t("deleteConfirm")}
        description={t("deleteDescription")}
        confirmLabel={tc("delete")}
        cancelLabel={tc("cancel")}
        loading={remove.isPending}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting);
        }}
      />
    </div>
  );
}
