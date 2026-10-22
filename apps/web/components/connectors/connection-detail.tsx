"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  CodeBlock,
  ConfirmDialog,
  Dialog,
  DialogContent,
  ErrorState,
  Field,
  Input,
  PageHeader,
  SkeletonRows,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  toast,
} from "@messer/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, Pencil, RefreshCw, Server, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { ApiError, http } from "@/lib/api";
import { formatDate, localeTag } from "@/lib/format";
import { useRole } from "@/lib/hooks/use-me";

import { ActionsPanel } from "./actions-panel";
import { ConnectorIcon, StatusBadge } from "./connector-icon";
import { McpTools } from "./mcp-tools";
import { connectorKeys, errorMessage, useAgents, useConnection, useConnector } from "./queries";
import { SchemaViewer } from "./schema-viewer";
import { SyncsPanel } from "./syncs-panel";
import type { Connection, OAuthStartResponse, TestResponse } from "./types";
import { WebhookPanel } from "./webhook-panel";

export function ConnectionDetail({ connectionId }: { connectionId: string }) {
  const t = useTranslations("connectors.detail");
  const tc = useTranslations("common");
  const tconn = useTranslations("connectors.connections");
  const router = useRouter();
  const qc = useQueryClient();
  const canBuild = useRole("builder");
  const canDelete = useRole("admin");
  const connection = useConnection(connectionId);
  const connector = useConnector(connection.data?.connector_key);
  const [removing, setRemoving] = React.useState(false);
  const [renaming, setRenaming] = React.useState(false);

  const test = useMutation({
    mutationFn: () => http.post<TestResponse>(`/connections/${connectionId}/test`),
    onSuccess: (res) => {
      if (res.ok) toast.success(tconn("testOk", { message: res.message }));
      else toast.error(tconn("testFailed", { message: res.message }));
      void qc.invalidateQueries({ queryKey: connectorKeys.connection(connectionId) });
      void qc.invalidateQueries({ queryKey: connectorKeys.connections });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });
  const reconnect = useMutation({
    mutationFn: (conn: Connection) =>
      http.post<OAuthStartResponse>(`/connections/oauth/${conn.connector_key}/start`, {
        connection_id: conn.id,
        return_to: "/app/connectors",
      }),
    onSuccess: (res) => {
      if (res.url) window.location.assign(res.url);
    },
    onError: (err) => toast.error(errorMessage(err)),
  });
  const remove = useMutation({
    mutationFn: () => http.del(`/connections/${connectionId}`),
    onSuccess: () => {
      toast.success(tconn("disconnected"));
      void qc.invalidateQueries({ queryKey: connectorKeys.connections });
      router.push("/app/connectors");
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  if (connection.isLoading) return <SkeletonRows rows={6} />;
  if (connection.error || !connection.data) {
    const notFound = connection.error instanceof ApiError && connection.error.status === 404;
    return (
      <ErrorState
        title={notFound ? t("notFound") : tc("errorTitle")}
        description={notFound ? undefined : tc("errorGeneric")}
        onRetry={notFound ? undefined : () => void connection.refetch()}
        retryLabel={tc("retry")}
      />
    );
  }
  const conn = connection.data;
  const caps = connector.data?.capabilities;
  const showSyncs = Boolean(caps?.sync);
  const showSchema = Boolean(caps?.introspection);
  const showWebhook = conn.connector_key === "webhooks";
  const showTools = conn.connector_key === "mcp";
  const oauthLive = conn.auth_type === "oauth2" && connector.data?.availability.mode === "oauth";

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        breadcrumbs={
          <Link href="/app/connectors" className="hover:text-fg">
            {t("back")}
          </Link>
        }
        title={
          <span className="flex items-center gap-2.5">
            <ConnectorIcon icon={connector.data?.icon} />
            {conn.name}
            <StatusBadge status={conn.status} />
          </span>
        }
        description={connector.data?.description ?? conn.connector_name}
        actions={
          <>
            {canBuild ? (
              <Button variant="secondary" onClick={() => test.mutate()} loading={test.isPending}>
                <FlaskConical />
                {tconn("test")}
              </Button>
            ) : null}
            {canBuild && oauthLive ? (
              <Button variant="secondary" onClick={() => reconnect.mutate(conn)} loading={reconnect.isPending}>
                <RefreshCw />
                {t("reconnect")}
              </Button>
            ) : null}
            {canBuild ? (
              <Button variant="ghost" onClick={() => setRenaming(true)} aria-label={t("rename")}>
                <Pencil />
              </Button>
            ) : null}
            {canDelete ? (
              <Button variant="danger" onClick={() => setRemoving(true)}>
                <Trash2 />
                {tconn("disconnect")}
              </Button>
            ) : null}
          </>
        }
      />
      {conn.demo ? (
        <Alert tone="info" title={t("demoTitle")}>
          {t("demoBody", { vars: conn.missing_env.join(", ") || "—" })}
        </Alert>
      ) : null}
      {conn.error ? (
        <Alert tone="danger" title={t("error")}>
          {conn.error}
        </Alert>
      ) : null}

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">{t("tabs.overview")}</TabsTrigger>
          <TabsTrigger value="actions">{t("tabs.actions")}</TabsTrigger>
          {showSyncs ? <TabsTrigger value="syncs">{t("tabs.syncs")}</TabsTrigger> : null}
          {showSchema ? <TabsTrigger value="schema">{t("tabs.schema")}</TabsTrigger> : null}
          {showWebhook ? <TabsTrigger value="webhook">{t("tabs.webhook")}</TabsTrigger> : null}
          {showTools ? <TabsTrigger value="tools">{t("tabs.tools")}</TabsTrigger> : null}
        </TabsList>
        <TabsContent value="overview">
          <Overview conn={conn} />
        </TabsContent>
        <TabsContent value="actions">
          <ActionsPanel connection={conn} />
        </TabsContent>
        {showSyncs ? (
          <TabsContent value="syncs">
            <SyncsPanel connection={conn} />
          </TabsContent>
        ) : null}
        {showSchema ? (
          <TabsContent value="schema">
            <SchemaViewer connectionId={conn.id} />
          </TabsContent>
        ) : null}
        {showWebhook ? (
          <TabsContent value="webhook">
            <WebhookPanel connectionId={conn.id} />
          </TabsContent>
        ) : null}
        {showTools ? (
          <TabsContent value="tools">
            <McpTools connectionId={conn.id} />
          </TabsContent>
        ) : null}
      </Tabs>

      <RenameDialog conn={conn} open={renaming} onOpenChange={setRenaming} />
      <ConfirmDialog
        open={removing}
        onOpenChange={setRemoving}
        title={tconn("disconnectTitle", { name: conn.name })}
        description={tconn("disconnectDescription")}
        confirmLabel={tconn("disconnect")}
        cancelLabel={tc("cancel")}
        loading={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </div>
  );
}

function Overview({ conn }: { conn: Connection }) {
  const t = useTranslations("connectors.detail");
  const ta = useTranslations("connectors.authTypes");
  const locale = useLocale();
  const tag = localeTag(locale);
  const connector = useConnector(conn.connector_key);
  const agents = useAgents(false);
  const agent = conn.agent_id ? (agents.data ?? []).find((a) => a.id === conn.agent_id) : undefined;
  const configEntries = Object.entries(conn.config);
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardBody>
          <dl className="grid grid-cols-[10rem_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="text-fg-subtle">{t("connector")}</dt>
            <dd>{conn.connector_name}</dd>
            <dt className="text-fg-subtle">{t("authType")}</dt>
            <dd>{conn.auth_type ? ta(conn.auth_type) : "—"}</dd>
            <dt className="text-fg-subtle">{t("created")}</dt>
            <dd className="tabular">{formatDate(conn.created_at, tag, true)}</dd>
            <dt className="text-fg-subtle">{t("updated")}</dt>
            <dd className="tabular">{formatDate(conn.updated_at, tag, true)}</dd>
            {conn.agent_id ? (
              <>
                <dt className="text-fg-subtle">{t("agent")}</dt>
                <dd>
                  <Link href="/app/connectors/agents" className="inline-flex items-center gap-1 hover:underline">
                    <Server className="size-3.5" aria-hidden />
                    {agent?.name ?? conn.agent_id}
                  </Link>
                </dd>
              </>
            ) : null}
            {conn.scopes.length > 0 ? (
              <>
                <dt className="text-fg-subtle">{t("scopes")}</dt>
                <dd className="flex flex-wrap gap-1">
                  {conn.scopes.map((s) => (
                    <Badge key={s} tone="outline" className="font-mono">
                      {s.replace("https://www.googleapis.com/auth/", "")}
                    </Badge>
                  ))}
                </dd>
              </>
            ) : null}
          </dl>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title={t("config")} />
        <CardBody>
          {configEntries.length === 0 ? (
            <p className="text-sm text-fg-subtle">{t("noConfig")}</p>
          ) : (
            <CodeBlock code={JSON.stringify(conn.config, null, 2)} language="json" />
          )}
        </CardBody>
      </Card>
      {(connector.data?.events ?? []).length > 0 ? (
        <Card className="lg:col-span-2">
          <CardHeader title={t("events")} description={t("eventsHint")} />
          <CardBody>
            <ul className="grid gap-2 md:grid-cols-2">
              {(connector.data?.events ?? []).map((e) => (
                <li key={e.name} className="flex flex-col gap-0.5 rounded-md border border-border p-3">
                  <span className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium">{locale === "en" ? e.title_en : e.title}</span>
                    <Badge tone={e.delivery === "push" ? "success" : "neutral"}>{t(`delivery.${e.delivery}`)}</Badge>
                  </span>
                  <span className="font-mono text-xs text-fg-subtle">{e.name}</span>
                  <span className="text-xs text-fg-muted">{e.description}</span>
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>
      ) : null}
    </div>
  );
}

function RenameDialog({ conn, open, onOpenChange }: { conn: Connection; open: boolean; onOpenChange: (open: boolean) => void }) {
  const t = useTranslations("connectors.detail");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const [name, setName] = React.useState(conn.name);
  const rename = useMutation({
    mutationFn: () => http.patch<Connection>(`/connections/${conn.id}`, { name: name.trim() }),
    onSuccess: () => {
      toast.success(t("renamed"));
      onOpenChange(false);
      void qc.invalidateQueries({ queryKey: connectorKeys.connection(conn.id) });
      void qc.invalidateQueries({ queryKey: connectorKeys.connections });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title={t("rename")}
        footer={
          <>
            <Button variant="secondary" onClick={() => onOpenChange(false)}>
              {tc("cancel")}
            </Button>
            <Button type="submit" form="rename-form" variant="primary" loading={rename.isPending} disabled={!name.trim()}>
              {tc("save")}
            </Button>
          </>
        }
      >
        <form
          id="rename-form"
          onSubmit={(e) => {
            e.preventDefault();
            rename.mutate();
          }}
        >
          <Field label={tc("name")} htmlFor="rename-input">
            <Input id="rename-input" value={name} maxLength={200} onChange={(e) => setName(e.target.value)} autoFocus />
          </Field>
        </form>
      </DialogContent>
    </Dialog>
  );
}
