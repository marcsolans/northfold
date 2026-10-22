"use client";

import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  PageHeader,
  SkeletonRows,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  toast,
} from "@messer/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bot, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";
import { formatRelative, localeTag } from "@/lib/format";
import { useRole } from "@/lib/hooks/use-me";
import { errorMessage, studioKeys, useMembers } from "@/lib/studio/hooks";
import type { Member } from "@/lib/studio/types";

import { CreateAgentDialog } from "./create-agent-dialog";

export function AgentsList({ projectId }: { projectId: string }) {
  const t = useTranslations("studio.agents");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const canBuild = useRole("builder");
  const qc = useQueryClient();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const agents = useMembers(projectId, "agent");
  const [createOpen, setCreateOpen] = React.useState(false);
  const [deleting, setDeleting] = React.useState<Member | null>(null);

  React.useEffect(() => {
    if (params.get("new") === "1" && canBuild) {
      setCreateOpen(true);
      router.replace(pathname);
    }
  }, [params, canBuild, router, pathname]);

  const remove = useMutation({
    mutationFn: (name: string) => http.del(`/projects/${projectId}/workforce/${encodeURIComponent(name)}`),
    onSuccess: (_, name) => {
      setDeleting(null);
      toast.success(t("deleted", { name }));
      void qc.invalidateQueries({ queryKey: ["projects", projectId] });
      void qc.invalidateQueries({ queryKey: studioKeys.projects, exact: true });
    },
    onError: (err) => toast.error(errorMessage(err, tc("errorGeneric"))),
  });

  const createButton = canBuild ? (
    <Button variant="primary" onClick={() => setCreateOpen(true)}>
      <Plus />
      {t("new")}
    </Button>
  ) : null;

  const list = agents.data ?? [];
  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-6 md:px-6">
      <PageHeader title={t("title")} description={t("description")} actions={createButton} />
      {agents.isLoading ? (
        <Card className="p-4">
          <SkeletonRows rows={4} />
        </Card>
      ) : agents.error ? (
        <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void agents.refetch()} retryLabel={tc("retry")} />
      ) : list.length === 0 ? (
        <EmptyState icon={<Bot />} title={t("empty.title")} description={t("empty.description")} action={createButton} />
      ) : (
        <Card>
          <Table>
            <THead>
              <tr>
                <TH>{tc("name")}</TH>
                <TH className="hidden md:table-cell">{tc("description")}</TH>
                <TH>{t("version")}</TH>
                <TH className="hidden sm:table-cell">{tc("updated")}</TH>
                {canBuild ? <TH className="w-12" /> : null}
              </tr>
            </THead>
            <TBody>
              {list.map((agent) => (
                <TR key={agent.id}>
                  <TD>
                    <Link
                      href={`/app/projects/${projectId}/agents/${encodeURIComponent(agent.name)}`}
                      className="flex items-center gap-2 font-mono text-xs font-medium hover:underline"
                    >
                      <Bot className="size-4 text-fg-subtle" aria-hidden />
                      {agent.name}
                    </Link>
                  </TD>
                  <TD className="hidden max-w-md truncate text-fg-muted md:table-cell">{agent.description || "—"}</TD>
                  <TD>
                    <span className="flex items-center gap-1.5">
                      <Badge tone="outline">v{agent.current_version}</Badge>
                      {agent.source_mode === "code" ? <Badge tone="info">{t("codeMode")}</Badge> : null}
                    </span>
                  </TD>
                  <TD className="hidden text-fg-muted sm:table-cell">{formatRelative(agent.updated_at, locale)}</TD>
                  {canBuild ? (
                    <TD className="text-right">
                      <Button variant="ghost" size="icon-sm" aria-label={t("delete", { name: agent.name })} onClick={() => setDeleting(agent)}>
                        <Trash2 />
                      </Button>
                    </TD>
                  ) : null}
                </TR>
              ))}
            </TBody>
          </Table>
        </Card>
      )}
      <CreateAgentDialog projectId={projectId} open={createOpen} onOpenChange={setCreateOpen} existing={list.map((a) => a.name)} />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
        title={t("deleteTitle", { name: deleting?.name ?? "" })}
        description={t("deleteDescription")}
        confirmLabel={tc("delete")}
        cancelLabel={tc("cancel")}
        loading={remove.isPending}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting.name);
        }}
      />
    </div>
  );
}
