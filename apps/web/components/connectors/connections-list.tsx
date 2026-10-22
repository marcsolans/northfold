"use client";

import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  SkeletonRows,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  Tooltip,
  toast,
} from "@messer/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plug, Server } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";
import { formatRelative, localeTag } from "@/lib/format";
import { useRole } from "@/lib/hooks/use-me";

import { ConnectorIcon, StatusBadge } from "./connector-icon";
import { connectorKeys, errorMessage, useCatalog, useConnections } from "./queries";
import type { Connection, TestResponse } from "./types";

export function ConnectionsList({ onBrowse }: { onBrowse: () => void }) {
  const t = useTranslations("connectors.connections");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const canTest = useRole("builder");
  const canDelete = useRole("admin");
  const connections = useConnections();
  const catalog = useCatalog("", "all");
  const icons = new Map((catalog.data?.items ?? []).map((c) => [c.key, c.icon]));
  const [removing, setRemoving] = React.useState<Connection | null>(null);
  const [testing, setTesting] = React.useState<string | null>(null);

  const test = useMutation({
    mutationFn: (id: string) => http.post<TestResponse>(`/connections/${id}/test`),
    onMutate: (id) => setTesting(id),
    onSuccess: (res) => {
      if (res.ok) toast.success(t("testOk", { message: res.message }));
      else toast.error(t("testFailed", { message: res.message }));
      void qc.invalidateQueries({ queryKey: connectorKeys.connections });
    },
    onError: (err) => toast.error(errorMessage(err)),
    onSettled: () => setTesting(null),
  });
  const remove = useMutation({
    mutationFn: (id: string) => http.del(`/connections/${id}`),
    onSuccess: () => {
      toast.success(t("disconnected"));
      setRemoving(null);
      void qc.invalidateQueries({ queryKey: connectorKeys.connections });
      void qc.invalidateQueries({ queryKey: ["syncs"] });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  if (connections.isLoading) {
    return (
      <Card className="p-4">
        <SkeletonRows rows={4} />
      </Card>
    );
  }
  if (connections.error) {
    return <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void connections.refetch()} retryLabel={tc("retry")} />;
  }
  const rows = connections.data ?? [];
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<Plug />}
        title={t("empty")}
        description={t("emptyHint")}
        action={
          <Button variant="primary" onClick={onBrowse}>
            {t("browse")}
          </Button>
        }
      />
    );
  }

  return (
    <Card>
      <Table>
        <THead>
          <tr>
            <TH>{tc("name")}</TH>
            <TH className="hidden md:table-cell">{t("connector")}</TH>
            <TH>{tc("status")}</TH>
            <TH className="hidden text-right lg:table-cell">{t("syncs")}</TH>
            <TH className="hidden lg:table-cell">{tc("created")}</TH>
            <TH className="w-48" />
          </tr>
        </THead>
        <TBody>
          {rows.map((c) => (
            <TR key={c.id}>
              <TD>
                <Link href={`/app/connectors/connections/${c.id}`} className="flex items-center gap-2.5 hover:underline">
                  <ConnectorIcon icon={icons.get(c.connector_key)} className="size-7" />
                  <span className="min-w-0">
                    <span className="block truncate font-medium">{c.name}</span>
                    {c.error ? <span className="block max-w-sm truncate text-xs text-danger">{c.error}</span> : null}
                  </span>
                </Link>
              </TD>
              <TD className="hidden text-fg-muted md:table-cell">
                <span className="flex items-center gap-1.5">
                  {c.connector_name}
                  {c.agent_id ? (
                    <Badge tone="outline" className="gap-1">
                      <Server className="size-3" aria-hidden />
                      {t("viaAgent")}
                    </Badge>
                  ) : null}
                </span>
              </TD>
              <TD>
                {c.demo && c.missing_env.length > 0 ? (
                  <Tooltip content={t("demoMissing", { vars: c.missing_env.join(", ") })}>
                    <span tabIndex={0}>
                      <StatusBadge status="demo" />
                    </span>
                  </Tooltip>
                ) : (
                  <StatusBadge status={c.status} />
                )}
              </TD>
              <TD className="tabular hidden text-right text-fg-muted lg:table-cell">{c.sync_count ?? 0}</TD>
              <TD className="hidden text-fg-muted lg:table-cell">{formatRelative(c.created_at, locale)}</TD>
              <TD className="text-right">
                <div className="flex justify-end gap-1">
                  {canTest ? (
                    <Button size="sm" variant="ghost" loading={testing === c.id} onClick={() => test.mutate(c.id)}>
                      {t("test")}
                    </Button>
                  ) : null}
                  <Button asChild size="sm" variant="ghost">
                    <Link href={`/app/connectors/connections/${c.id}`}>{t("open")}</Link>
                  </Button>
                  {canDelete ? (
                    <Button size="sm" variant="ghost" onClick={() => setRemoving(c)}>
                      {t("disconnect")}
                    </Button>
                  ) : null}
                </div>
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={t("disconnectTitle", { name: removing?.name ?? "" })}
        description={t("disconnectDescription")}
        confirmLabel={t("disconnect")}
        cancelLabel={tc("cancel")}
        loading={remove.isPending}
        onConfirm={() => {
          if (removing) remove.mutate(removing.id);
        }}
      />
    </Card>
  );
}
