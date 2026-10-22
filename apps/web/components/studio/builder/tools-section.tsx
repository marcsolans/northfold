"use client";

import {
  Alert,
  Badge,
  Button,
  Dialog,
  DialogContent,
  Field,
  Input,
  Select,
  SkeletonRows,
  Switch,
  cn,
} from "@messer/ui";
import { useQueries } from "@tanstack/react-query";
import { Check, Lock, Plug, Plus, Search, Server, Trash2, Wrench } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";
import {
  LOCKED_APPROVAL,
  builtinTool,
  connectorToolName,
  defaultMcpServer,
  secretRefs,
  toolIdentity,
} from "@/lib/studio/agent-config";
import { useConnectionsOptional, useToolsCatalog } from "@/lib/studio/hooks";
import {
  type AgentConfig,
  type ConnectionSummary,
  type ConnectorAction,
  type KnowledgeBaseSummary,
  MCP_APPROVALS,
  type McpApproval,
  type McpServerConfig,
  type ToolCatalogItem,
  type ToolConfig,
} from "@/lib/studio/types";
import type { Role } from "@/lib/types";

import { Section, TagInput } from "./fields";

const ROLES: Role[] = ["owner", "admin", "builder", "viewer"];

function useToolLabel(catalog: ToolCatalogItem[] | undefined) {
  const t = useTranslations("studio.tools.builtin");
  return (tool: Pick<ToolConfig, "type" | "key" | "config" | "name">) => {
    if (tool.type === "builtin") {
      if (t.has(`${tool.key}.label`)) return t(`${tool.key}.label`);
      return catalog?.find((c) => c.key === tool.key)?.label ?? tool.key;
    }
    const title = tool.config.title;
    return typeof title === "string" && title ? title : (tool.name ?? tool.key);
  };
}

// ------------------------------------------------------------------------------------ picker

function ToolPicker({
  projectId,
  open,
  onOpenChange,
  existing,
  onAdd,
}: {
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  existing: Set<string>;
  onAdd: (tool: ToolConfig) => void;
}) {
  const t = useTranslations("studio.tools");
  const tb = useTranslations("studio.tools.builtin");
  const tc = useTranslations("common");
  const [query, setQuery] = React.useState("");
  const catalog = useToolsCatalog(projectId);
  const connections = useConnectionsOptional(open);
  const actionQueries = useQueries({
    queries: (connections.data ?? []).map((c) => ({
      queryKey: ["connections", c.id, "actions"],
      queryFn: () => http.get<ConnectorAction[]>(`/connections/${c.id}/actions`),
      staleTime: 60_000,
      enabled: open,
    })),
  });
  const label = useToolLabel(catalog.data);

  React.useEffect(() => {
    if (open) setQuery("");
  }, [open]);

  const q = query.trim().toLowerCase();
  const matches = (...texts: (string | undefined)[]) => !q || texts.some((x) => x?.toLowerCase().includes(q));

  const builtin = (catalog.data ?? []).filter((item) => {
    const desc = tb.has(`${item.key}.description`) ? tb(`${item.key}.description`) : "";
    return matches(item.key, item.label, label({ type: "builtin", key: item.key, config: {}, name: null }), desc);
  });

  const add = (tool: ToolConfig) => {
    onAdd(tool);
    onOpenChange(false);
  };

  const connectorGroups: { connection: ConnectionSummary; actions: ConnectorAction[]; loading: boolean; failed: boolean }[] =
    (connections.data ?? []).map((connection, i) => {
      const res = actionQueries[i];
      return {
        connection,
        actions: (res?.data ?? []).filter((a) => matches(a.name, a.title, a.description, connection.name, connection.connector_name)),
        loading: Boolean(res?.isLoading),
        failed: Boolean(res?.error),
      };
    });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={t("pickerTitle")} description={t("pickerDescription")} wide>
        <div className="relative mb-4">
          <Search className="pointer-events-none absolute left-2.5 top-2 size-4 text-fg-subtle" aria-hidden />
          <Input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("searchPlaceholder")}
            aria-label={tc("search")}
            className="pl-8"
          />
        </div>
        <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-fg-subtle">{t("groups.builtin")}</h3>
        {catalog.isLoading ? (
          <SkeletonRows rows={4} />
        ) : catalog.error ? (
          <Alert tone="danger">{t("catalogError")}</Alert>
        ) : builtin.length === 0 ? (
          <p className="text-sm text-fg-subtle">{t("noMatches")}</p>
        ) : (
          <ul className="grid gap-2 sm:grid-cols-2">
            {builtin.map((item) => {
              const tool = builtinTool(item);
              const added = existing.has(toolIdentity(tool));
              return (
                <li key={item.key}>
                  <button
                    type="button"
                    disabled={added}
                    onClick={() => add(tool)}
                    className="flex w-full items-start gap-2.5 rounded-md border border-border p-2.5 text-left hover:border-border-strong hover:bg-subtle disabled:cursor-default disabled:opacity-60 disabled:hover:bg-transparent"
                  >
                    <Wrench className="mt-0.5 size-4 shrink-0 text-fg-subtle" aria-hidden />
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-1.5 text-sm font-medium">
                        {label(tool)}
                        {item.side_effect ? <Badge tone="warning">{t("sideEffect")}</Badge> : null}
                      </span>
                      {tb.has(`${item.key}.description`) ? (
                        <span className="mt-0.5 block text-xs text-fg-muted">{tb(`${item.key}.description`)}</span>
                      ) : null}
                    </span>
                    {added ? (
                      <span className="flex items-center gap-1 text-xs text-fg-subtle">
                        <Check className="size-3.5" />
                        {t("added")}
                      </span>
                    ) : null}
                  </button>
                </li>
              );
            })}
          </ul>
        )}

        {connections.data === null ? null : (
          <>
            <h3 className="mb-2 mt-5 text-xs font-medium uppercase tracking-wide text-fg-subtle">{t("groups.connectors")}</h3>
            {connections.isLoading ? (
              <SkeletonRows rows={2} />
            ) : connections.error ? (
              <Alert tone="danger">{t("connectionsError")}</Alert>
            ) : connectorGroups.length === 0 ? (
              <p className="text-sm text-fg-subtle">{t("noConnections")}</p>
            ) : (
              <div className="flex flex-col gap-4">
                {connectorGroups.map(({ connection, actions, loading, failed }) => (
                  <div key={connection.id}>
                    <p className="mb-1.5 flex items-center gap-1.5 text-sm font-medium">
                      <Plug className="size-4 text-fg-subtle" aria-hidden />
                      {connection.name}
                      <span className="text-xs font-normal text-fg-subtle">· {connection.connector_name}</span>
                      {connection.demo ? <Badge tone="info">{tc("demoMode")}</Badge> : null}
                    </p>
                    {loading ? (
                      <SkeletonRows rows={2} />
                    ) : failed ? (
                      <p className="text-xs text-danger">{t("actionsError")}</p>
                    ) : actions.length === 0 ? (
                      <p className="text-xs text-fg-subtle">{t("noMatches")}</p>
                    ) : (
                      <ul className="grid gap-2 sm:grid-cols-2">
                        {actions.map((action) => {
                          const tool: ToolConfig = {
                            type: "connector",
                            key: action.name,
                            name: connectorToolName(connection.connector_key, action.name),
                            connection_id: connection.id,
                            description: action.description,
                            input_schema: action.input_schema ?? { type: "object", properties: {} },
                            requires_approval: action.requires_approval ?? action.side_effect,
                            approver_role: "admin",
                            config: { title: action.title, connector_key: connection.connector_key, connection_name: connection.name },
                          };
                          const added = existing.has(toolIdentity(tool));
                          return (
                            <li key={action.name}>
                              <button
                                type="button"
                                disabled={added}
                                onClick={() => add(tool)}
                                className="flex w-full items-start gap-2.5 rounded-md border border-border p-2.5 text-left hover:border-border-strong hover:bg-subtle disabled:cursor-default disabled:opacity-60"
                              >
                                <span className="min-w-0 flex-1">
                                  <span className="flex items-center gap-1.5 text-sm font-medium">
                                    {action.title || action.name}
                                    {action.side_effect ? <Badge tone="warning">{t("sideEffect")}</Badge> : null}
                                  </span>
                                  {action.description ? (
                                    <span className="mt-0.5 line-clamp-2 block text-xs text-fg-muted">{action.description}</span>
                                  ) : null}
                                </span>
                                {added ? <Check className="size-3.5 text-fg-subtle" aria-label={t("added")} /> : null}
                              </button>
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

// ------------------------------------------------------------------------------------ tool row

function ToolRow({
  tool,
  index,
  label,
  sideEffect,
  readOnly,
  knowledgeBases,
  onChange,
  onRemove,
}: {
  tool: ToolConfig;
  index: number;
  label: string;
  sideEffect: boolean;
  readOnly: boolean;
  knowledgeBases: KnowledgeBaseSummary[] | null;
  onChange: (tool: ToolConfig) => void;
  onRemove: () => void;
}) {
  const t = useTranslations("studio.tools");
  const tc = useTranslations("common");
  const locked = tool.type === "builtin" ? LOCKED_APPROVAL[tool.key] : undefined;
  const approvalOn = locked ? true : tool.requires_approval;
  const id = `tool-${index}`;
  const setConfig = (patch: Record<string, unknown>) => onChange({ ...tool, config: { ...tool.config, ...patch } });
  const hosts = Array.isArray(tool.config.allowed_hosts) ? (tool.config.allowed_hosts as string[]) : [];
  const connectionName = typeof tool.config.connection_name === "string" ? tool.config.connection_name : null;

  return (
    <li className="rounded-md border border-border">
      <div className="flex items-start gap-2.5 p-3">
        {tool.type === "connector" ? (
          <Plug className="mt-0.5 size-4 shrink-0 text-fg-subtle" aria-hidden />
        ) : (
          <Wrench className="mt-0.5 size-4 shrink-0 text-fg-subtle" aria-hidden />
        )}
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-1.5 text-sm font-medium">
            {label}
            <Badge tone="outline">{t(`types.${tool.type}`)}</Badge>
            {sideEffect ? <Badge tone="warning">{t("sideEffect")}</Badge> : null}
          </p>
          <p className="mt-0.5 font-mono text-[11px] text-fg-subtle">
            {tool.name ?? tool.key}
            {connectionName ? ` · ${connectionName}` : ""}
          </p>
        </div>
        {readOnly ? null : (
          <Button size="icon-sm" variant="ghost" aria-label={t("remove", { name: label })} onClick={onRemove}>
            <Trash2 />
          </Button>
        )}
      </div>
      <div className="flex flex-col gap-3 border-t border-border bg-subtle/60 px-3 py-2.5">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <label htmlFor={`${id}-approval`} className="flex items-center gap-2 text-sm">
            <Switch
              id={`${id}-approval`}
              checked={approvalOn}
              disabled={readOnly || Boolean(locked)}
              onCheckedChange={(checked) => onChange({ ...tool, requires_approval: checked })}
            />
            {t("requiresApproval")}
            {locked ? <Lock className="size-3.5 text-fg-subtle" aria-hidden /> : null}
          </label>
          {approvalOn ? (
            <div className="flex items-center gap-2">
              <label htmlFor={`${id}-role`} className="text-xs text-fg-muted">
                {t("approver")}
              </label>
              <div className="w-40">
                <Select
                  id={`${id}-role`}
                  aria-label={t("approver")}
                  value={tool.approver_role}
                  disabled={readOnly}
                  onValueChange={(v) => onChange({ ...tool, approver_role: v as Role })}
                  options={ROLES.map((r) => ({ value: r, label: t("approverRole", { role: tc(`roles.${r}`) }) }))}
                />
              </div>
            </div>
          ) : null}
        </div>
        {locked ? <p className="text-xs text-fg-subtle">{t(`locked.${locked}`)}</p> : null}
        {tool.type === "builtin" && (tool.key === "read_url" || tool.key === "http_request") ? (
          <Field label={t("allowedHosts")} htmlFor={`${id}-hosts`} hint={t("allowedHostsHint")}>
            <TagInput
              id={`${id}-hosts`}
              values={hosts}
              disabled={readOnly}
              placeholder="api.example.com"
              removeLabel={(host) => t("removeHost", { host })}
              onChange={(list) => setConfig({ allowed_hosts: list.length ? list : undefined })}
            />
          </Field>
        ) : null}
        {tool.type === "builtin" && tool.key === "current_datetime" ? (
          <Field label={t("timezone")} htmlFor={`${id}-tz`}>
            <Input
              id={`${id}-tz`}
              value={typeof tool.config.timezone === "string" ? tool.config.timezone : ""}
              readOnly={readOnly}
              placeholder="Europe/Madrid"
              onChange={(e) => setConfig({ timezone: e.target.value.trim() || undefined })}
            />
          </Field>
        ) : null}
        {tool.type === "builtin" && tool.key === "sql_query" && knowledgeBases && knowledgeBases.length > 0 ? (
          <Field label={t("sqlKb")} htmlFor={`${id}-kb`}>
            <Select
              id={`${id}-kb`}
              aria-label={t("sqlKb")}
              value={typeof tool.config.kb_id === "string" ? tool.config.kb_id : undefined}
              placeholder={t("sqlKbPlaceholder")}
              disabled={readOnly}
              onValueChange={(v) => setConfig({ kb_id: v })}
              options={knowledgeBases.map((kb) => ({ value: kb.id, label: kb.name }))}
            />
          </Field>
        ) : null}
      </div>
    </li>
  );
}

// ------------------------------------------------------------------------------------ MCP servers

function McpRow({
  server,
  index,
  readOnly,
  error,
  onChange,
  onRemove,
}: {
  server: McpServerConfig;
  index: number;
  readOnly: boolean;
  error: string | null;
  onChange: (server: McpServerConfig) => void;
  onRemove: () => void;
}) {
  const t = useTranslations("studio.tools.mcp");
  const id = `mcp-${index}`;
  const headers = Object.entries(server.headers);
  const setHeader = (i: number, key: string, value: string) => {
    const next = headers.map(([k, v], j) => (j === i ? [key, value] : [k, v]) as [string, string]);
    onChange({ ...server, headers: Object.fromEntries(next) });
  };
  const refs = [...new Set(Object.values(server.headers).flatMap(secretRefs))];
  return (
    <li className="rounded-md border border-border p-3">
      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_auto]">
        <Field label={t("name")} htmlFor={`${id}-name`}>
          <Input
            id={`${id}-name`}
            value={server.name}
            readOnly={readOnly}
            className="font-mono text-xs"
            onChange={(e) => onChange({ ...server, name: e.target.value.toLowerCase().replace(/[\s-]+/g, "_") })}
          />
        </Field>
        <Field label={t("url")} htmlFor={`${id}-url`}>
          <Input
            id={`${id}-url`}
            value={server.url}
            readOnly={readOnly}
            inputMode="url"
            placeholder="https://mcp.example.com/mcp"
            onChange={(e) => onChange({ ...server, url: e.target.value.trim() })}
          />
        </Field>
        <div className="flex items-end">
          {readOnly ? null : (
            <Button size="icon-sm" variant="ghost" aria-label={t("remove", { name: server.name })} onClick={onRemove}>
              <Trash2 />
            </Button>
          )}
        </div>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <Field label={t("approval")} htmlFor={`${id}-approval`}>
          <Select
            id={`${id}-approval`}
            aria-label={t("approval")}
            value={server.approval}
            disabled={readOnly}
            onValueChange={(v) => onChange({ ...server, approval: v as McpApproval })}
            options={MCP_APPROVALS.map((value) => ({
              value,
              label: t(`approvals.${value}.label`),
              description: t(`approvals.${value}.description`),
            }))}
          />
        </Field>
      </div>
      <div className="mt-3">
        <div className="mb-1.5 flex items-center justify-between">
          <span className="text-sm font-medium">{t("headers")}</span>
          {readOnly ? null : (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                let n = headers.length + 1;
                while (`X-Header-${n}` in server.headers) n += 1;
                onChange({ ...server, headers: { ...server.headers, [headers.length === 0 ? "Authorization" : `X-Header-${n}`]: "" } });
              }}
            >
              <Plus />
              {t("addHeader")}
            </Button>
          )}
        </div>
        {headers.length === 0 ? (
          <p className="text-xs text-fg-subtle">{t("noHeaders")}</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {headers.map(([key, value], i) => (
              <li key={i} className="grid grid-cols-[minmax(0,1fr)_minmax(0,2fr)_auto] gap-2">
                <Input
                  aria-label={t("headerName")}
                  value={key}
                  readOnly={readOnly}
                  className="font-mono text-xs"
                  onChange={(e) => setHeader(i, e.target.value, value)}
                />
                <Input
                  aria-label={t("headerValue")}
                  value={value}
                  readOnly={readOnly}
                  className="font-mono text-xs"
                  placeholder="Bearer $API_TOKEN"
                  onChange={(e) => setHeader(i, key, e.target.value)}
                />
                {readOnly ? (
                  <span />
                ) : (
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    aria-label={t("removeHeader", { name: key })}
                    onClick={() => onChange({ ...server, headers: Object.fromEntries(headers.filter((_, j) => j !== i)) })}
                  >
                    <Trash2 />
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
        <p className="mt-1.5 text-xs text-fg-subtle">
          {refs.length > 0 ? t("secretsUsed", { names: refs.map((r) => `$${r}`).join(", ") }) : t("headersHint")}
        </p>
      </div>
      {error ? (
        <p className="mt-2 text-xs text-danger" role="alert">
          {error}
        </p>
      ) : null}
    </li>
  );
}

// ------------------------------------------------------------------------------------ section

export function ToolsSection({
  projectId,
  config,
  onChange,
  readOnly,
  knowledgeBases,
  mcpErrors,
}: {
  projectId: string;
  config: AgentConfig;
  onChange: (patch: Partial<AgentConfig>) => void;
  readOnly: boolean;
  knowledgeBases: KnowledgeBaseSummary[] | null;
  mcpErrors: Record<number, string>;
}) {
  const t = useTranslations("studio.tools");
  const tm = useTranslations("studio.tools.mcp");
  const catalog = useToolsCatalog(projectId);
  const label = useToolLabel(catalog.data);
  const [pickerOpen, setPickerOpen] = React.useState(false);
  const existing = React.useMemo(() => new Set(config.tools.map(toolIdentity)), [config.tools]);
  const sideEffectOf = (tool: ToolConfig) =>
    tool.type === "builtin"
      ? Boolean(catalog.data?.find((c) => c.key === tool.key)?.side_effect)
      : tool.type === "connector" && tool.requires_approval;

  return (
    <Section
      id="tools"
      title={t("title")}
      description={t("description")}
      actions={
        readOnly ? null : (
          <Button size="sm" variant="secondary" onClick={() => setPickerOpen(true)}>
            <Plus />
            {t("add")}
          </Button>
        )
      }
    >
      {config.tools.length === 0 ? (
        <p className="rounded-md border border-dashed border-border-strong px-3 py-4 text-center text-sm text-fg-subtle">
          {t("empty")}
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {config.tools.map((tool, i) => (
            <ToolRow
              key={toolIdentity(tool)}
              tool={tool}
              index={i}
              label={label(tool)}
              sideEffect={sideEffectOf(tool)}
              readOnly={readOnly}
              knowledgeBases={knowledgeBases}
              onChange={(next) => onChange({ tools: config.tools.map((x, j) => (j === i ? next : x)) })}
              onRemove={() => onChange({ tools: config.tools.filter((_, j) => j !== i) })}
            />
          ))}
        </ul>
      )}
      {config.tools.some((tool) => tool.type === "builtin" && tool.key === "knowledge_search") &&
      config.knowledge_bases.length === 0 &&
      knowledgeBases !== null ? (
        <Alert tone="warning">{t("knowledgeSearchNoKb")}</Alert>
      ) : null}

      <div className={cn("rounded-md border border-border")}>
        <div className="flex items-start justify-between gap-3 border-b border-border px-3 py-2.5">
          <div>
            <h3 className="flex items-center gap-1.5 text-sm font-semibold">
              <Server className="size-4 text-fg-subtle" aria-hidden />
              {tm("title")}
            </h3>
            <p className="mt-0.5 text-xs text-fg-muted">{tm("description")}</p>
          </div>
          {readOnly ? null : (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onChange({ mcp_servers: [...config.mcp_servers, defaultMcpServer(config.mcp_servers)] })}
            >
              <Plus />
              {tm("add")}
            </Button>
          )}
        </div>
        <div className="p-3">
          {config.mcp_servers.length === 0 ? (
            <p className="text-xs text-fg-subtle">{tm("empty")}</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {config.mcp_servers.map((server, i) => (
                <McpRow
                  key={i}
                  server={server}
                  index={i}
                  readOnly={readOnly}
                  error={mcpErrors[i] ?? null}
                  onChange={(next) => onChange({ mcp_servers: config.mcp_servers.map((x, j) => (j === i ? next : x)) })}
                  onRemove={() => onChange({ mcp_servers: config.mcp_servers.filter((_, j) => j !== i) })}
                />
              ))}
            </ul>
          )}
        </div>
      </div>

      <ToolPicker
        projectId={projectId}
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        existing={existing}
        onAdd={(tool) => onChange({ tools: [...config.tools, tool] })}
      />
    </Section>
  );
}
