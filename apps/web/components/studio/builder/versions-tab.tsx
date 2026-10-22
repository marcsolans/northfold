"use client";

import {
  Alert,
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Select,
  Skeleton,
  SkeletonRows,
  toast,
} from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { GitCompare, History, RotateCcw, Save } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { ApiError, http } from "@/lib/api";
import { formatDate, formatRelative, localeTag } from "@/lib/format";
import { shortHash } from "@/lib/studio/format";
import { errorMessage, studioKeys, useVersions } from "@/lib/studio/hooks";
import type { FileContent, FileList, MemberDetail, Version } from "@/lib/studio/types";

import { DiffViewer, languageFor } from "../monaco";

async function fileAt(projectId: string, path: string, ref: string): Promise<string> {
  try {
    return (await http.get<FileContent>(`/projects/${projectId}/files/content`, { path, ref })).content;
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return "";
    throw err;
  }
}

function DiffPanel({
  projectId,
  member,
  version,
  versions,
  onClose,
}: {
  projectId: string;
  member: MemberDetail;
  version: Version;
  versions: Version[];
  onClose: () => void;
}) {
  const t = useTranslations("studio.builder.versions");
  const tc = useTranslations("common");
  const [against, setAgainst] = React.useState<string>("HEAD");
  const mainFile = `${member.path}/${member.kind === "agent" ? "agent.py" : "workflow.py"}`;
  const [file, setFile] = React.useState(mainFile);
  const targetRef = against === "HEAD" ? "HEAD" : (versions.find((v) => String(v.version) === against)?.git_commit ?? "HEAD");

  const files = useQuery({
    queryKey: ["projects", projectId, "files", version.git_commit, targetRef, member.path],
    queryFn: async () => {
      const [a, b] = await Promise.all([
        http.get<FileList>(`/projects/${projectId}/files`, { ref: version.git_commit }),
        http.get<FileList>(`/projects/${projectId}/files`, { ref: targetRef }),
      ]);
      const prefix = `${member.path}/`;
      return [...new Set([...a.files, ...b.files])].filter((f) => f.startsWith(prefix)).sort();
    },
  });
  const contents = useQuery({
    queryKey: ["projects", projectId, "diff", version.git_commit, targetRef, file],
    queryFn: async () => {
      const [original, modified] = await Promise.all([
        fileAt(projectId, file, version.git_commit),
        fileAt(projectId, file, targetRef),
      ]);
      return { original, modified };
    },
  });

  return (
    <div className="mt-4 rounded-md border border-border">
      <div className="flex flex-wrap items-end gap-3 border-b border-border px-3 py-2.5">
        <p className="mr-auto text-sm font-semibold">{t("diffTitle", { version: version.version })}</p>
        <div className="w-44">
          <Select
            aria-label={t("compareWith")}
            value={against}
            onValueChange={setAgainst}
            options={[
              { value: "HEAD", label: t("current") },
              ...versions.filter((v) => v.id !== version.id).map((v) => ({ value: String(v.version), label: `v${v.version}` })),
            ]}
          />
        </div>
        <div className="w-64">
          <Select
            aria-label={t("file")}
            value={file}
            onValueChange={setFile}
            options={(files.data ?? [mainFile]).map((f) => ({ value: f, label: f.slice(member.path.length + 1) }))}
          />
        </div>
        <Button size="sm" variant="ghost" onClick={onClose}>
          {tc("close")}
        </Button>
      </div>
      <div className="flex justify-between px-3 py-1.5 text-xs text-fg-subtle">
        <span>
          v{version.version} · <span className="font-mono">{shortHash(version.git_commit)}</span>
        </span>
        <span>{against === "HEAD" ? t("current") : `v${against}`}</span>
      </div>
      <div className="h-[26rem]">
        {contents.isLoading ? (
          <Skeleton className="h-full w-full rounded-none" />
        ) : contents.error ? (
          <div className="p-3">
            <ErrorState title={tc("errorTitle")} description={errorMessage(contents.error, tc("errorGeneric"))} onRetry={() => void contents.refetch()} retryLabel={tc("retry")} />
          </div>
        ) : contents.data && contents.data.original === contents.data.modified ? (
          <p className="p-4 text-sm text-fg-subtle">{t("noChanges")}</p>
        ) : (
          <DiffViewer
            original={contents.data?.original ?? ""}
            modified={contents.data?.modified ?? ""}
            language={languageFor(file)}
            ariaLabel={t("diffTitle", { version: version.version })}
          />
        )}
      </div>
    </div>
  );
}

export function VersionsTab({
  projectId,
  member,
  canBuild,
  dirty,
  onRestored,
}: {
  projectId: string;
  member: MemberDetail;
  canBuild: boolean;
  dirty: boolean;
  onRestored: (detail: MemberDetail) => void;
}) {
  const t = useTranslations("studio.builder.versions");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const versions = useVersions(projectId, member.name);
  const [message, setMessage] = React.useState("");
  const [comparing, setComparing] = React.useState<Version | null>(null);
  const [restoring, setRestoring] = React.useState<Version | null>(null);
  const base = `/projects/${projectId}/workforce/${encodeURIComponent(member.name)}`;

  const save = useMutation({
    mutationFn: () => http.post<Version>(`${base}/versions`, { message: message.trim() }),
    onSuccess: (v) => {
      setMessage("");
      toast.success(t("saved", { version: v.version }));
      void qc.invalidateQueries({ queryKey: studioKeys.versions(projectId, member.name) });
      void qc.invalidateQueries({ queryKey: studioKeys.member(projectId, member.name) });
    },
    onError: (err) => toast.error(errorMessage(err, tc("errorGeneric"))),
  });

  const restore = useMutation({
    mutationFn: (v: Version) => http.post<MemberDetail>(`${base}/versions/${v.version}/restore`),
    onSuccess: (detail, v) => {
      setRestoring(null);
      setComparing(null);
      toast.success(t("restored", { version: v.version }));
      onRestored(detail);
      void qc.invalidateQueries({ queryKey: ["projects", projectId, "files"] });
      void qc.invalidateQueries({ queryKey: ["projects", projectId, "diff"] });
    },
    onError: (err) => toast.error(errorMessage(err, tc("errorGeneric"))),
  });

  const list = versions.data ?? [];
  return (
    <div className="px-4 py-4 md:px-5">
      {canBuild ? (
        <form
          className="flex flex-col gap-2 rounded-md border border-border p-3 sm:flex-row sm:items-end"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <Field label={t("message")} htmlFor="version-message" className="flex-1" hint={dirty ? t("dirtyHint") : t("messageHint")}>
            <Input
              id="version-message"
              value={message}
              maxLength={500}
              placeholder={t("messagePlaceholder", { version: member.current_version + 1 })}
              onChange={(e) => setMessage(e.target.value)}
            />
          </Field>
          <Button type="submit" variant="primary" loading={save.isPending} disabled={dirty} className="sm:mb-[22px]">
            <Save />
            {t("save")}
          </Button>
        </form>
      ) : null}

      <div className="mt-4">
        {versions.isLoading ? (
          <SkeletonRows rows={3} />
        ) : versions.error ? (
          <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void versions.refetch()} retryLabel={tc("retry")} />
        ) : list.length === 0 ? (
          <EmptyState icon={<History />} title={t("empty.title")} description={t("empty.description")} />
        ) : (
          <ol className="divide-y divide-border rounded-md border border-border">
            {list.map((v) => (
              <li key={v.id} className="flex flex-wrap items-center gap-3 px-3 py-2.5">
                <Badge tone={v.version === member.current_version ? "accent" : "outline"}>v{v.version}</Badge>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{v.message || t("noMessage")}</p>
                  <p className="text-xs text-fg-subtle">
                    <time dateTime={v.created_at} title={formatDate(v.created_at, locale, true)}>
                      {formatRelative(v.created_at, locale)}
                    </time>{" "}
                    · <span className="font-mono">{shortHash(v.git_commit)}</span>
                  </p>
                </div>
                <Button size="sm" variant="ghost" aria-pressed={comparing?.id === v.id} onClick={() => setComparing(comparing?.id === v.id ? null : v)}>
                  <GitCompare />
                  {t("compare")}
                </Button>
                {canBuild ? (
                  <Button size="sm" variant="secondary" onClick={() => setRestoring(v)}>
                    <RotateCcw />
                    {t("restore")}
                  </Button>
                ) : null}
              </li>
            ))}
          </ol>
        )}
      </div>

      {comparing ? (
        <DiffPanel projectId={projectId} member={member} version={comparing} versions={list} onClose={() => setComparing(null)} />
      ) : null}

      <ConfirmDialog
        open={restoring !== null}
        onOpenChange={(open) => {
          if (!open) setRestoring(null);
        }}
        title={t("restoreTitle", { version: restoring?.version ?? 0 })}
        description={t("restoreDescription")}
        confirmLabel={t("restore")}
        cancelLabel={tc("cancel")}
        loading={restore.isPending}
        onConfirm={() => {
          if (restoring) restore.mutate(restoring);
        }}
      >
        {dirty ? <Alert tone="warning">{t("restoreDirty")}</Alert> : null}
      </ConfirmDialog>
    </div>
  );
}
