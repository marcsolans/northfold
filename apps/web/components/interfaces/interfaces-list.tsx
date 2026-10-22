"use client";

import {
  Badge,
  Button,
  ConfirmDialog,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  EmptyState,
  ErrorState,
  PageHeader,
  Skeleton,
  toast,
} from "@messer/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ExternalLink, LayoutDashboard, MessageSquare, MoreHorizontal, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";
import { formatRelative, localeTag } from "@/lib/format";
import { useRole } from "@/lib/hooks/use-me";

import { interfaceKeys, useInterfaces } from "./api";
import { CreateInterfaceDialog } from "./create-interface-dialog";
import type { InterfaceSummary } from "./types";
import { messageOf } from "./util";

/** Interfaces of a project: dashboards and apps, and public chats (with their public URLs once published). */
export function InterfacesList({ projectId }: { projectId: string }) {
  const t = useTranslations("interfaces");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const canBuild = useRole("builder");
  const qc = useQueryClient();
  const list = useInterfaces(projectId);
  const [createOpen, setCreateOpen] = React.useState(false);
  const [deleting, setDeleting] = React.useState<InterfaceSummary | null>(null);

  const remove = useMutation({
    mutationFn: (id: string) => http.del(`/interfaces/${id}`),
    onSuccess: () => {
      toast.success(t("list.deleted", { name: deleting?.name ?? "" }));
      setDeleting(null);
      void qc.invalidateQueries({ queryKey: interfaceKeys.list(projectId) });
    },
    onError: (err) => toast.error(messageOf(err, tc("errorGeneric"))),
  });

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-6 md:px-6">
      <PageHeader
        title={t("list.title")}
        description={t("list.description")}
        actions={
          canBuild ? (
            <Button variant="primary" onClick={() => setCreateOpen(true)}>
              <Plus />
              {t("list.new")}
            </Button>
          ) : null
        }
      />
      {list.isPending ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" role="status" aria-label={tc("loading")}>
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-36" />
          ))}
        </div>
      ) : list.error ? (
        <ErrorState title={tc("errorTitle")} description={messageOf(list.error, tc("errorGeneric"))} onRetry={() => void list.refetch()} retryLabel={tc("retry")} />
      ) : list.data.length === 0 ? (
        <EmptyState
          icon={<LayoutDashboard />}
          title={t("list.emptyTitle")}
          description={t("list.emptyDescription")}
          action={
            canBuild ? (
              <Button variant="primary" onClick={() => setCreateOpen(true)}>
                <Plus />
                {t("list.new")}
              </Button>
            ) : null
          }
        />
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {list.data.map((item) => {
            const Icon = item.kind === "chat" ? MessageSquare : LayoutDashboard;
            return (
              <li key={item.id} className="group relative flex flex-col gap-3 rounded-md border border-border bg-surface p-4 hover:border-border-strong">
                <div className="flex items-start gap-3">
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-md border border-border bg-subtle text-fg-muted">
                    <Icon className="size-4" aria-hidden />
                  </span>
                  <div className="min-w-0 flex-1">
                    <Link
                      href={`/app/projects/${projectId}/interfaces/${item.id}`}
                      className="block truncate text-sm font-semibold text-fg after:absolute after:inset-0 hover:underline"
                    >
                      {item.name}
                    </Link>
                    <p className="truncate font-mono text-xs text-fg-subtle">{item.slug}</p>
                  </div>
                  {canBuild ? (
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon-sm" aria-label={t("list.actions", { name: item.name })} className="relative z-[1]">
                          <MoreHorizontal />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onSelect={() => setDeleting(item)} className="text-danger">
                          <Trash2 />
                          {tc("delete")}
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  ) : null}
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge>{t(`kinds.${item.kind}`)}</Badge>
                  {item.published ? <Badge tone="success">{t("list.published")}</Badge> : <Badge tone="outline">{t("list.draft")}</Badge>}
                  {item.auth_required ? <Badge tone="outline">{t("list.loginRequired")}</Badge> : <Badge tone="outline">{t("list.publicAccess")}</Badge>}
                  {!item.valid ? (
                    <Badge tone="danger">
                      <AlertTriangle className="size-3" aria-hidden />
                      {t("list.invalid")}
                    </Badge>
                  ) : null}
                </div>
                <div className="mt-auto flex items-center justify-between gap-2 text-xs text-fg-muted">
                  <span>
                    {item.kind === "chat"
                      ? t("list.agent", { agent: item.workforce_name ?? "—" })
                      : t("list.components", { count: item.components, screens: item.screens })}
                    {" · "}
                    {formatRelative(item.updated_at, locale)}
                  </span>
                  {item.published && item.urls.public ? (
                    <a
                      href={item.urls.public}
                      target="_blank"
                      rel="noreferrer"
                      className="relative z-[1] inline-flex items-center gap-1 font-medium text-accent hover:underline"
                    >
                      {t("list.open")}
                      <ExternalLink className="size-3" aria-hidden />
                    </a>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      <CreateInterfaceDialog projectId={projectId} open={createOpen} onOpenChange={setCreateOpen} />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => (open ? undefined : setDeleting(null))}
        title={t("list.deleteTitle")}
        description={deleting?.published ? t("list.deletePublished", { name: deleting.name }) : t("list.deleteDescription", { name: deleting?.name ?? "" })}
        confirmLabel={tc("delete")}
        cancelLabel={tc("cancel")}
        loading={remove.isPending}
        onConfirm={() => (deleting ? remove.mutateAsync(deleting.id).then(() => undefined) : undefined)}
      />
    </div>
  );
}
