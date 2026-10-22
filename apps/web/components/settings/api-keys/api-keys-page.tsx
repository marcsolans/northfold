"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  PageHeader,
  SkeletonRows,
  StatusDot,
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
import { Ban, KeyRound, Plus } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { useUpgradeDialog } from "@/components/billing";
import { ApiError, http } from "@/lib/api";
import { formatDate, formatRelative, localeTag } from "@/lib/format";
import { useMe } from "@/lib/hooks/use-me";
import { useProjects } from "@/lib/studio/hooks";
import { hasRole } from "@/lib/types";

import { CreateKeyDialog, useScopeLabel } from "./create-key-dialog";
import { type ApiKey, apiKeysKeys } from "./types";

/** Settings → API keys: list (read-only for builders), create with a show-once panel and revoke (admins). */
export function ApiKeysPage() {
  const t = useTranslations("apiKeys");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const me = useMe();
  const canRead = hasRole(me.data, "builder");
  const isAdmin = hasRole(me.data, "admin");
  const upgrade = useUpgradeDialog();
  const scopeLabel = useScopeLabel();

  const keys = useQuery({ queryKey: apiKeysKeys.list, queryFn: () => http.get<ApiKey[]>("/api-keys"), enabled: canRead });
  const projects = useProjects();
  const projectName = React.useMemo(() => new Map((projects.data ?? []).map((p) => [p.id, p.name])), [projects.data]);

  const [createOpen, setCreateOpen] = React.useState(false);
  const [revoking, setRevoking] = React.useState<ApiKey | null>(null);

  const revoke = useMutation({
    mutationFn: (key: ApiKey) => http.del(`/api-keys/${key.id}`),
    onSuccess: (_data, key) => {
      const now = new Date().toISOString();
      qc.setQueryData(apiKeysKeys.list, (prev: ApiKey[] | undefined) =>
        (prev ?? []).map((k) => (k.id === key.id ? { ...k, revoked_at: k.revoked_at ?? now } : k)),
      );
      void qc.invalidateQueries({ queryKey: apiKeysKeys.list, exact: true });
      setRevoking(null);
      toast.success(t("revoked", { name: key.name }));
    },
    onError: (err) => {
      setRevoking(null);
      if (upgrade.handle(err)) return;
      toast.error(err instanceof ApiError ? err.message || tc("errorGeneric") : tc("errorGeneric"));
    },
  });

  let body: React.ReactNode;
  if (me.isLoading) {
    body = <SkeletonRows rows={4} />;
  } else if (me.error) {
    body = <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void me.refetch()} retryLabel={tc("retry")} />;
  } else if (!canRead) {
    body = <Alert tone="info">{t("viewerNotice")}</Alert>;
  } else if (keys.isLoading) {
    body = <SkeletonRows rows={4} />;
  } else if (keys.error) {
    body = <ErrorState title={tc("errorTitle")} description={t("loadError")} onRetry={() => void keys.refetch()} retryLabel={tc("retry")} />;
  } else if (!keys.data?.length) {
    body = (
      <EmptyState
        icon={<KeyRound />}
        title={t("empty.title")}
        description={isAdmin ? t("empty.description") : t("empty.descriptionReadOnly")}
        action={
          isAdmin ? (
            <Button variant="primary" onClick={() => setCreateOpen(true)}>
              <Plus />
              {t("createButton")}
            </Button>
          ) : undefined
        }
      />
    );
  } else {
    body = (
      <Card>
        <Table aria-label={t("tableLabel")}>
          <THead>
            <tr>
              <TH>{t("columns.name")}</TH>
              <TH>{t("columns.prefix")}</TH>
              <TH className="hidden md:table-cell">{t("columns.project")}</TH>
              <TH>{t("columns.scopes")}</TH>
              <TH className="hidden lg:table-cell">{t("columns.lastUsed")}</TH>
              <TH className="hidden lg:table-cell">{t("columns.created")}</TH>
              <TH>{t("columns.status")}</TH>
              {isAdmin ? (
                <TH className="text-right">
                  <span className="sr-only">{tc("actions")}</span>
                </TH>
              ) : null}
            </tr>
          </THead>
          <TBody>
            {keys.data.map((k) => {
              const revoked = Boolean(k.revoked_at);
              return (
                <TR key={k.id} className={cn(revoked && "text-fg-muted")}>
                  <TD className={cn("max-w-[14rem] truncate font-medium", revoked && "text-fg-muted")}>{k.name}</TD>
                  <TD className="whitespace-nowrap font-mono text-xs">{k.prefix}…</TD>
                  <TD className="hidden max-w-[12rem] truncate md:table-cell">
                    {k.project_id ? (projectName.get(k.project_id) ?? <span className="font-mono text-xs">{k.project_id.slice(0, 8)}</span>) : (
                      <span className="text-fg-muted">{t("allProjects")}</span>
                    )}
                  </TD>
                  <TD>
                    {k.scopes.length === 0 ? (
                      <span className="text-xs text-fg-muted">{t("allScopes")}</span>
                    ) : (
                      <div className="flex max-w-[18rem] flex-wrap gap-1">
                        {k.scopes.map((s) => (
                          <Badge key={s} tone="outline" className="font-mono" title={scopeLabel(s).label}>
                            {s}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </TD>
                  <TD className="hidden whitespace-nowrap text-fg-muted lg:table-cell">
                    {k.last_used_at ? (
                      <time dateTime={k.last_used_at} title={formatDate(k.last_used_at, locale, true)}>
                        {formatRelative(k.last_used_at, locale)}
                      </time>
                    ) : (
                      t("neverUsed")
                    )}
                  </TD>
                  <TD className="hidden whitespace-nowrap text-fg-muted lg:table-cell">
                    <time dateTime={k.created_at} title={formatDate(k.created_at, locale, true)}>
                      {formatDate(k.created_at, locale)}
                    </time>
                  </TD>
                  <TD className="whitespace-nowrap">
                    {revoked && k.revoked_at ? (
                      <Badge tone="danger" title={formatDate(k.revoked_at, locale, true)}>
                        <StatusDot tone="danger" />
                        {t("status.revoked", { date: formatDate(k.revoked_at, locale) })}
                      </Badge>
                    ) : (
                      <Badge tone="success">
                        <StatusDot tone="success" />
                        {t("status.active")}
                      </Badge>
                    )}
                  </TD>
                  {isAdmin ? (
                    <TD className="text-right">
                      {!revoked ? (
                        <Button size="sm" variant="danger" onClick={() => setRevoking(k)} aria-label={t("revokeFor", { name: k.name })}>
                          <Ban />
                          {t("revoke")}
                        </Button>
                      ) : null}
                    </TD>
                  ) : null}
                </TR>
              );
            })}
          </TBody>
        </Table>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title={t("title")}
        description={t("description")}
        className="pb-0"
        actions={
          isAdmin ? (
            <Button variant="primary" onClick={() => setCreateOpen(true)}>
              <Plus />
              {t("createButton")}
            </Button>
          ) : null
        }
      />
      {canRead && !isAdmin ? <Alert tone="info">{t("readOnly")}</Alert> : null}
      {body}
      <p className="text-xs text-fg-subtle">{t("footnote")}</p>

      {isAdmin ? <CreateKeyDialog open={createOpen} onOpenChange={setCreateOpen} /> : null}
      <ConfirmDialog
        open={revoking !== null}
        onOpenChange={(open) => {
          if (!open && !revoke.isPending) setRevoking(null);
        }}
        title={t("revokeTitle", { name: revoking?.name ?? "" })}
        description={t("revokeDescription")}
        confirmLabel={t("revoke")}
        cancelLabel={tc("cancel")}
        loading={revoke.isPending}
        onConfirm={() => {
          if (revoking) revoke.mutate(revoking);
        }}
      />
      {upgrade.dialog}
    </div>
  );
}
