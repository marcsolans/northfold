"use client";

import {
  Badge,
  Button,
  Card,
  CodeBlock,
  ConfirmDialog,
  Dialog,
  DialogContent,
  EmptyState,
  ErrorState,
  Field,
  Input,
  PageHeader,
  SkeletonRows,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  toast,
} from "@messer/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Plus, Server } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";
import { formatRelative, localeTag } from "@/lib/format";
import { useRole } from "@/lib/hooks/use-me";

import { StatusBadge } from "./connector-icon";
import { connectorKeys, errorMessage, useAgents } from "./queries";
import type { AgentItem, EnrollmentResponse } from "./types";

const AGENT_CONFIG_EXAMPLE = `sources:
  erp:
    type: postgresql        # postgresql | mysql | sqlserver
    dsn_env: ERP_DSN        # postgresql://reader:…@10.0.0.5:5432/erp
paths:
  - /srv/documentos
max_file_mb: 25`;

export function AgentsPanel() {
  const t = useTranslations("connectors.agents");
  const tc = useTranslations("common");
  const tb = useTranslations("connectors");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const isAdmin = useRole("admin");
  const canPing = useRole("builder");
  const agents = useAgents(true);
  const [creating, setCreating] = React.useState(false);
  const [name, setName] = React.useState("");
  const [enrollment, setEnrollment] = React.useState<EnrollmentResponse | null>(null);
  const [deleting, setDeleting] = React.useState<AgentItem | null>(null);

  const create = useMutation({
    mutationFn: () => http.post<EnrollmentResponse>("/connector-agents", { name: name.trim() }),
    onSuccess: (res) => {
      setCreating(false);
      setName("");
      setEnrollment(res);
      void qc.invalidateQueries({ queryKey: connectorKeys.agents });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });
  const regenerate = useMutation({
    mutationFn: (id: string) => http.post<EnrollmentResponse>(`/connector-agents/${id}/enrollment-token`),
    onSuccess: (res) => setEnrollment(res),
    onError: (err) => toast.error(errorMessage(err)),
  });
  const ping = useMutation({
    mutationFn: (id: string) => http.post<{ ok: boolean; latency_ms: number }>(`/connector-agents/${id}/ping`),
    onSuccess: (res) => {
      toast.success(t("pingOk", { ms: res.latency_ms }));
      void qc.invalidateQueries({ queryKey: connectorKeys.agents });
    },
    onError: (err) => toast.error(t("pingFailed", { message: errorMessage(err) })),
  });
  const remove = useMutation({
    mutationFn: (id: string) => http.del(`/connector-agents/${id}`),
    onSuccess: () => {
      toast.success(t("deleted"));
      setDeleting(null);
      void qc.invalidateQueries({ queryKey: connectorKeys.agents });
      void qc.invalidateQueries({ queryKey: connectorKeys.connections });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  let body: React.ReactNode;
  if (agents.isLoading) body = <SkeletonRows rows={3} />;
  else if (agents.error) {
    body = <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void agents.refetch()} retryLabel={tc("retry")} />;
  } else if ((agents.data ?? []).length === 0) {
    body = (
      <EmptyState
        icon={<Server />}
        title={t("empty")}
        description={t("emptyHint")}
        action={
          isAdmin ? (
            <Button variant="primary" onClick={() => setCreating(true)}>
              <Plus />
              {t("new")}
            </Button>
          ) : null
        }
      />
    );
  } else {
    body = (
      <Card>
        <Table>
          <THead>
            <tr>
              <TH>{t("name")}</TH>
              <TH>{t("status")}</TH>
              <TH className="hidden md:table-cell">{t("host")}</TH>
              <TH className="hidden lg:table-cell">{t("sources")}</TH>
              <TH className="hidden md:table-cell">{t("lastSeen")}</TH>
              <TH className="hidden text-right lg:table-cell">{t("connections")}</TH>
              <TH className="w-64" />
            </tr>
          </THead>
          <TBody>
            {(agents.data ?? []).map((a) => (
              <TR key={a.id}>
                <TD>
                  <span className="font-medium">{a.name}</span>
                  {a.version ? <span className="block text-xs text-fg-subtle">v{a.version}</span> : null}
                </TD>
                <TD>
                  <StatusBadge status={a.status} />
                </TD>
                <TD className="hidden text-fg-muted md:table-cell">
                  {a.hostname ?? "—"}
                  {a.capabilities.platform ? <span className="block text-xs text-fg-subtle">{a.capabilities.platform}</span> : null}
                </TD>
                <TD className="hidden lg:table-cell">
                  <div className="flex flex-wrap gap-1">
                    {(a.capabilities.sources ?? []).map((s) => (
                      <Badge key={s.name} tone="outline" className="font-mono">
                        {s.name}:{s.type}
                      </Badge>
                    ))}
                    {(a.capabilities.paths ?? []).map((p) => (
                      <Badge key={p} tone="outline" className="font-mono">
                        {p}
                      </Badge>
                    ))}
                  </div>
                </TD>
                <TD className="hidden text-fg-muted md:table-cell">
                  {a.last_seen_at ? formatRelative(a.last_seen_at, locale) : t("never")}
                </TD>
                <TD className="tabular hidden text-right text-fg-muted lg:table-cell">{a.connections}</TD>
                <TD className="text-right">
                  <div className="flex justify-end gap-1">
                    {canPing && a.status === "online" ? (
                      <Button size="sm" variant="ghost" loading={ping.isPending && ping.variables === a.id} onClick={() => ping.mutate(a.id)}>
                        {t("ping")}
                      </Button>
                    ) : null}
                    {isAdmin ? (
                      <>
                        <Button
                          size="sm"
                          variant="ghost"
                          loading={regenerate.isPending && regenerate.variables === a.id}
                          onClick={() => regenerate.mutate(a.id)}
                        >
                          <KeyRound />
                          {t("newToken")}
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setDeleting(a)}>
                          {t("delete")}
                        </Button>
                      </>
                    ) : null}
                  </div>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        breadcrumbs={
          <Link href="/app/connectors" className="hover:text-fg">
            {tb("title")}
          </Link>
        }
        title={t("title")}
        description={t("description")}
        actions={
          isAdmin && (agents.data ?? []).length > 0 ? (
            <Button variant="primary" onClick={() => setCreating(true)}>
              <Plus />
              {t("new")}
            </Button>
          ) : null
        }
      />
      {body}

      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent
          title={t("new")}
          description={t("description")}
          footer={
            <>
              <Button variant="secondary" onClick={() => setCreating(false)}>
                {tc("cancel")}
              </Button>
              <Button type="submit" form="agent-form" variant="primary" loading={create.isPending} disabled={!name.trim()}>
                {t("create")}
              </Button>
            </>
          }
        >
          <form
            id="agent-form"
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate();
            }}
          >
            <Field label={t("name")} htmlFor="agent-name">
              <Input id="agent-name" value={name} maxLength={200} placeholder={t("namePlaceholder")} onChange={(e) => setName(e.target.value)} autoFocus />
            </Field>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={enrollment !== null} onOpenChange={(open) => !open && setEnrollment(null)}>
        {enrollment ? (
          <DialogContent
            wide
            title={t("enrollTitle")}
            description={t("enrollIntro")}
            footer={
              <Button variant="primary" onClick={() => setEnrollment(null)}>
                {t("done")}
              </Button>
            }
          >
            <div className="flex flex-col gap-4">
              <Tabs defaultValue="binary">
                <TabsList>
                  <TabsTrigger value="binary">{t("binary")}</TabsTrigger>
                  <TabsTrigger value="python">{t("python")}</TabsTrigger>
                  <TabsTrigger value="docker">{t("docker")}</TabsTrigger>
                </TabsList>
                <TabsContent value="binary">
                  <CodeBlock code={`${enrollment.commands.binary}\n${enrollment.commands.run}`} language="bash" />
                </TabsContent>
                <TabsContent value="python">
                  <CodeBlock code={`${enrollment.commands.python}\npython -m messer_connector_agent run`} language="bash" />
                </TabsContent>
                <TabsContent value="docker">
                  <CodeBlock code={enrollment.commands.docker} language="bash" />
                </TabsContent>
              </Tabs>
              <div className="flex flex-col gap-1">
                <p className="text-sm font-medium">{t("configTitle")}</p>
                <p className="text-sm text-fg-muted">{t("configIntro")}</p>
                <CodeBlock code={AGENT_CONFIG_EXAMPLE} language="yaml" />
              </div>
            </div>
          </DialogContent>
        ) : null}
      </Dialog>

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={t("deleteTitle", { name: deleting?.name ?? "" })}
        description={t("deleteDescription")}
        confirmLabel={t("delete")}
        cancelLabel={tc("cancel")}
        loading={remove.isPending}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting.id);
        }}
      />
    </div>
  );
}
