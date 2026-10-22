"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  ConfirmDialog,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  EmptyState,
  ErrorState,
  Input,
  SkeletonRows,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  cn,
  toast,
} from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileText, MoreHorizontal, RefreshCw, Table2, Trash2, UploadCloud } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { apiUrl, http } from "@/lib/api";
import { formatRelative, localeTag } from "@/lib/format";

import { FileStatus } from "./file-status";
import { errorMessage, formatBytes, kbKeys } from "./queries";
import type { FileList, KbFile, KnowledgeBase } from "./types";
import { uploadKnowledgeFile } from "./upload";
import type { LiveFileState } from "./use-kb-events";

const MAX_FILE_MB = 100;
const CONCURRENCY = 3;
const ACCEPT = ".pdf,.docx,.pptx,.xlsx,.xlsm,.csv,.tsv,.html,.htm,.md,.markdown,.txt,.json,.xml,.eml";
type StatusFilter = "all" | "processing" | "ready" | "error";

interface PendingUpload {
  key: string;
  name: string;
  size: number;
  progress: number;
  state: "waiting" | "uploading" | "error";
  error?: string;
}

export function FilesTab({
  kb,
  canWrite,
  live,
  onOpenTable,
}: {
  kb: KnowledgeBase;
  canWrite: boolean;
  live: Record<string, LiveFileState>;
  onOpenTable: (tableId: string) => void;
}) {
  const t = useTranslations("knowledge.files");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const [filter, setFilter] = React.useState<StatusFilter>("all");
  const [query, setQuery] = React.useState("");
  const [dragging, setDragging] = React.useState(false);
  const [pending, setPending] = React.useState<PendingUpload[]>([]);
  const [deleting, setDeleting] = React.useState<KbFile | null>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);

  const files = useQuery({
    queryKey: [...kbKeys.files(kb.id), filter, query],
    queryFn: () =>
      http.get<FileList>(`/knowledge-bases/${kb.id}/files`, {
        status: filter === "all" ? undefined : filter,
        q: query.trim() || undefined,
        limit: 200,
      }),
  });

  const invalidate = React.useCallback(() => {
    void qc.invalidateQueries({ queryKey: kbKeys.files(kb.id) });
    void qc.invalidateQueries({ queryKey: kbKeys.detail(kb.id), exact: true });
  }, [qc, kb.id]);

  const reprocess = useMutation({
    mutationFn: (file: KbFile) => http.post<KbFile>(`/knowledge-bases/${kb.id}/files/${file.id}/reprocess`),
    onSuccess: (file) => {
      toast.success(t("reprocessQueued", { name: file.filename }));
      invalidate();
    },
    onError: (err) => toast.error(errorMessage(err)),
  });
  const remove = useMutation({
    mutationFn: (file: KbFile) => http.del(`/knowledge-bases/${kb.id}/files/${file.id}`),
    onSuccess: () => {
      setDeleting(null);
      toast.success(t("deleted"));
      invalidate();
      void qc.invalidateQueries({ queryKey: kbKeys.tables(kb.id) });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const startUploads = React.useCallback(
    (list: File[]) => {
      if (list.length === 0) return;
      const entries = list.map((file) => {
        const key = `${file.name}-${file.size}-${Math.random().toString(36).slice(2)}`;
        const tooLarge = file.size > MAX_FILE_MB * 1024 * 1024;
        return {
          file,
          entry: {
            key,
            name: file.name,
            size: file.size,
            progress: 0,
            state: tooLarge ? "error" : "waiting",
            error: tooLarge ? t("tooLarge", { max: MAX_FILE_MB }) : undefined,
          } satisfies PendingUpload,
        };
      });
      setPending((prev) => [...entries.map((e) => e.entry), ...prev]);
      const queue = entries.filter((e) => e.entry.state === "waiting");
      const update = (key: string, patch: Partial<PendingUpload>) =>
        setPending((prev) => prev.map((p) => (p.key === key ? { ...p, ...patch } : p)));
      const worker = async () => {
        for (;;) {
          const next = queue.shift();
          if (!next) return;
          update(next.entry.key, { state: "uploading" });
          try {
            const result = await uploadKnowledgeFile(`/knowledge-bases/${kb.id}/files`, next.file, (progress) =>
              update(next.entry.key, { progress }),
            );
            const rejected = result.errors[0];
            if (rejected) {
              update(next.entry.key, { state: "error", error: rejected.message });
            } else {
              setPending((prev) => prev.filter((p) => p.key !== next.entry.key));
              invalidate();
            }
          } catch (err) {
            update(next.entry.key, { state: "error", error: errorMessage(err) });
          }
        }
      };
      void Promise.all(Array.from({ length: Math.min(CONCURRENCY, queue.length) }, worker));
    },
    [kb.id, invalidate, t],
  );

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (!canWrite) return;
    startUploads(Array.from(e.dataTransfer.files));
  };

  const items = files.data?.items ?? [];
  const filters: StatusFilter[] = ["all", "processing", "ready", "error"];

  return (
    <div className="flex flex-col gap-4">
      {canWrite ? (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={cn(
            "flex flex-col items-center justify-center gap-2 rounded-md border border-dashed border-border-strong px-6 py-8 text-center transition-colors",
            dragging && "border-accent bg-accent-soft",
          )}
        >
          <UploadCloud className="size-6 text-fg-subtle" aria-hidden />
          <p className="text-sm font-medium">{t("dropTitle")}</p>
          <p className="max-w-lg text-xs text-fg-muted">{t("dropHint", { max: MAX_FILE_MB })}</p>
          <Button size="sm" variant="secondary" onClick={() => inputRef.current?.click()}>
            {t("browse")}
          </Button>
          <input
            ref={inputRef}
            type="file"
            multiple
            accept={ACCEPT}
            className="sr-only"
            aria-label={t("browse")}
            onChange={(e) => {
              startUploads(Array.from(e.target.files ?? []));
              e.target.value = "";
            }}
          />
        </div>
      ) : null}

      {pending.length > 0 ? (
        <Card>
          <ul className="divide-y divide-border">
            {pending.map((p) => (
              <li key={p.key} className="flex items-center justify-between gap-3 px-4 py-2 text-sm">
                <span className="flex min-w-0 items-center gap-2">
                  <FileText className="size-4 shrink-0 text-fg-subtle" aria-hidden />
                  <span className="truncate">{p.name}</span>
                  <span className="tabular shrink-0 text-xs text-fg-subtle">{formatBytes(p.size, locale)}</span>
                </span>
                {p.state === "error" ? (
                  <span className="flex items-center gap-2">
                    <span className="text-xs text-danger">{p.error}</span>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setPending((prev) => prev.filter((x) => x.key !== p.key))}
                    >
                      {tc("close")}
                    </Button>
                  </span>
                ) : (
                  <FileStatus status="uploading" progress={p.state === "waiting" ? 0 : p.progress} />
                )}
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-1" role="group" aria-label={tc("status")}>
          {filters.map((f) => (
            <Button key={f} size="sm" variant={filter === f ? "dark" : "ghost"} onClick={() => setFilter(f)} aria-pressed={filter === f}>
              {t(`filter.${f}`)}
            </Button>
          ))}
        </div>
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("searchPlaceholder")}
          aria-label={t("searchPlaceholder")}
          className="max-w-xs"
        />
      </div>

      <Card>
        {files.isLoading ? (
          <div className="p-4">
            <SkeletonRows rows={4} />
          </div>
        ) : files.error ? (
          <div className="p-4">
            <ErrorState title={tc("errorTitle")} description={errorMessage(files.error)} onRetry={() => void files.refetch()} retryLabel={tc("retry")} />
          </div>
        ) : items.length === 0 ? (
          <div className="p-4">
            <EmptyState
              icon={<FileText />}
              title={filter === "all" && !query ? t("empty.title") : t("empty.filtered")}
              description={filter === "all" && !query ? t("empty.description") : undefined}
            />
          </div>
        ) : (
          <Table>
            <THead>
              <tr>
                <TH>{t("columns.name")}</TH>
                <TH>{tc("status")}</TH>
                <TH className="hidden md:table-cell">{t("columns.size")}</TH>
                <TH className="hidden md:table-cell">{t("columns.content")}</TH>
                <TH className="hidden lg:table-cell">{t("columns.source")}</TH>
                <TH className="hidden lg:table-cell">{tc("created")}</TH>
                <TH className="w-12" />
              </tr>
            </THead>
            <TBody>
              {items.map((file) => {
                const state = live[file.id];
                const status = state && state.status !== file.status && file.status !== "ready" && file.status !== "error" ? state.status : file.status;
                return (
                  <TR key={file.id}>
                    <TD className="max-w-xs">
                      <span className="flex min-w-0 items-center gap-2">
                        {file.table_id ? (
                          <Table2 className="size-4 shrink-0 text-fg-subtle" aria-hidden />
                        ) : (
                          <FileText className="size-4 shrink-0 text-fg-subtle" aria-hidden />
                        )}
                        <span className="truncate font-medium" title={file.filename}>
                          {file.filename}
                        </span>
                      </span>
                    </TD>
                    <TD>
                      <FileStatus status={status} progress={state?.progress} error={file.error ?? state?.error} />
                    </TD>
                    <TD className="tabular hidden text-fg-muted md:table-cell">{formatBytes(file.size, locale)}</TD>
                    <TD className="hidden text-fg-muted md:table-cell">
                      {file.table_id ? (
                        <button type="button" className="text-accent underline-offset-4 hover:underline" onClick={() => onOpenTable(file.table_id ?? "")}>
                          {t("openTable")}
                        </button>
                      ) : file.status === "ready" ? (
                        <span className="tabular">
                          {t("chunkCount", { count: file.chunk_count })}
                          {file.pages ? ` · ${t("pageCount", { count: file.pages })}` : ""}
                        </span>
                      ) : (
                        "—"
                      )}
                    </TD>
                    <TD className="hidden lg:table-cell">
                      <Badge tone="outline">{t(`source.${file.source === "connector" || file.source === "agent" ? file.source : "upload"}`)}</Badge>
                    </TD>
                    <TD className="hidden text-fg-muted lg:table-cell">{formatRelative(file.created_at, locale)}</TD>
                    <TD className="text-right">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon-sm" aria-label={tc("actions")}>
                            <MoreHorizontal />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem asChild>
                            <a href={apiUrl(`/knowledge-bases/${kb.id}/files/${file.id}/download`)} download={file.filename}>
                              <Download />
                              {t("download")}
                            </a>
                          </DropdownMenuItem>
                          {canWrite ? (
                            <>
                              <DropdownMenuItem
                                disabled={file.status !== "ready" && file.status !== "error"}
                                onSelect={() => reprocess.mutate(file)}
                              >
                                <RefreshCw />
                                {t("reprocess")}
                              </DropdownMenuItem>
                              <DropdownMenuSeparator />
                              <DropdownMenuItem destructive onSelect={() => setDeleting(file)}>
                                <Trash2 />
                                {tc("delete")}
                              </DropdownMenuItem>
                            </>
                          ) : null}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TD>
                  </TR>
                );
              })}
            </TBody>
          </Table>
        )}
      </Card>
      {files.data && files.data.total > items.length ? (
        <Alert tone="info">{t("showing", { shown: items.length, total: files.data.total })}</Alert>
      ) : null}

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={t("deleteConfirm", { name: deleting?.filename ?? "" })}
        description={deleting?.table_id ? t("deleteTableDescription") : t("deleteDescription")}
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
