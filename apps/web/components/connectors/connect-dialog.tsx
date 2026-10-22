"use client";

import {
  Alert,
  Badge,
  Button,
  Dialog,
  DialogContent,
  Field,
  Input,
  RadioCards,
  Select,
  Switch,
  Textarea,
  toast,
} from "@messer/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";

import { ConnectorIcon } from "./connector-icon";
import { connectorKeys, errorMessage, useAgents } from "./queries";
import type { ConfigField, Connection, ConnectorItem, OAuthStartResponse } from "./types";

type Values = Record<string, string | boolean>;

function initialValues(fields: ConfigField[]): Values {
  const out: Values = {};
  for (const f of fields) {
    if (f.kind === "boolean") out[f.key] = f.default !== false;
    else if (f.kind === "select") out[f.key] = typeof f.default === "string" ? f.default : (f.options[0] ?? "");
    else out[f.key] = typeof f.default === "string" ? f.default : "";
  }
  return out;
}

/** Fields shown for the current MCP transport (URL + headers, or command + env). */
function visibleFields(connector: ConnectorItem, values: Values, viaAgent: boolean): ConfigField[] {
  return connector.config_fields.filter((f) => {
    if (connector.key === "mcp") {
      if (f.key === "transport") return true;
      const http = values.transport !== "stdio";
      return http ? f.key === "url" || f.key === "headers" : f.key === "command" || f.key === "env";
    }
    if (viaAgent && f.key === "connection_string") return false;
    return true;
  });
}

export function ConnectDialog({
  connector,
  open,
  onOpenChange,
}: {
  connector: ConnectorItem | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {connector ? <ConnectForm key={connector.key} connector={connector} onDone={() => onOpenChange(false)} /> : null}
    </Dialog>
  );
}

function ConnectForm({ connector, onDone }: { connector: ConnectorItem; onDone: () => void }) {
  const t = useTranslations("connectors.connect");
  const tc = useTranslations("common");
  const router = useRouter();
  const qc = useQueryClient();
  const [name, setName] = React.useState("");
  const [values, setValues] = React.useState<Values>(() => initialValues(connector.config_fields));
  const [viaAgent, setViaAgent] = React.useState(connector.auth_type === "agent");
  const [agentId, setAgentId] = React.useState("");
  const [agentSource, setAgentSource] = React.useState("");
  const [formError, setFormError] = React.useState<string | null>(null);
  const agentCapable = connector.capabilities.agent;
  const agents = useAgents(false);
  const enrolledAgents = (agents.data ?? []).filter((a) => a.status !== "pending");
  const selectedAgent = enrolledAgents.find((a) => a.id === agentId);
  const isOAuth = connector.auth_type === "oauth2";
  const demo = connector.availability.mode === "demo";

  const finish = async (conn: Connection) => {
    await qc.invalidateQueries({ queryKey: connectorKeys.connections });
    onDone();
    router.push(`/app/connectors/connections/${conn.id}`);
  };

  const mutation = useMutation({
    mutationFn: async () => {
      if (isOAuth) {
        return http.post<OAuthStartResponse>(`/connections/oauth/${connector.key}/start`, {
          name: name.trim() || null,
          return_to: "/app/connectors",
        });
      }
      const config: Record<string, unknown> = {};
      const credentials: Record<string, unknown> = {};
      for (const field of visibleFields(connector, values, viaAgent)) {
        const raw = values[field.key];
        let value: unknown;
        if (field.kind === "boolean") value = Boolean(raw);
        else if (field.kind === "json") {
          const text = String(raw ?? "").trim();
          if (!text) continue;
          try {
            value = JSON.parse(text);
          } catch {
            throw new Error(t("invalidJson", { field: t(`fields.${field.key}`) }));
          }
        } else if (field.kind === "list") {
          const items = String(raw ?? "")
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean);
          if (items.length === 0) continue;
          value = items;
        } else {
          value = String(raw ?? "").trim();
          if (value === "") continue;
        }
        if (field.secret) credentials[field.key] = value;
        else config[field.key] = value;
      }
      if (viaAgent) {
        if (connector.category === "database") config.agent_source = agentSource.trim();
      }
      const conn = await http.post<Connection>("/connections", {
        connector_key: connector.key,
        name: name.trim() || null,
        config,
        credentials,
        agent_id: viaAgent ? agentId || null : null,
      });
      return { mode: "created", connection: conn } as const;
    },
    onSuccess: async (res) => {
      if ("url" in res && res.mode === "oauth" && res.url) {
        toast.message(t("redirecting"));
        window.location.assign(res.url);
        return;
      }
      if (res.connection) {
        if (res.mode === "demo") toast.success(t("demoCreated"));
        else if (res.connection.status === "error") toast.error(res.connection.error ?? tc("errorGeneric"));
        else toast.success(t("title", { name: connector.name }));
        await finish(res.connection);
      }
    },
    onError: (err) => setFormError(errorMessage(err)),
  });

  const fields = visibleFields(connector, values, viaAgent);
  const set = (key: string, value: string | boolean) => setValues((v) => ({ ...v, [key]: value }));

  return (
    <DialogContent
      title={
        <span className="flex items-center gap-2">
          <ConnectorIcon icon={connector.icon} className="size-6" />
          {t("title", { name: connector.name })}
        </span>
      }
      description={connector.description}
      footer={
        <>
          <Button type="button" variant="secondary" onClick={onDone}>
            {tc("cancel")}
          </Button>
          <Button type="submit" form="connect-form" variant="primary" loading={mutation.isPending}>
            {t("submit")}
          </Button>
        </>
      }
    >
      <form
        id="connect-form"
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          setFormError(null);
          mutation.mutate();
        }}
      >
        {formError ? <Alert tone="danger">{formError}</Alert> : null}
        <Field label={t("name")} htmlFor="connection-name" hint={tc("optional")}>
          <Input
            id="connection-name"
            value={name}
            maxLength={200}
            placeholder={t("namePlaceholder", { name: connector.name })}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>

        {isOAuth ? (
          demo ? (
            <Alert tone="info" title={t("demoTitle")}>
              <p>{t("demoBody")}</p>
              <p className="mt-1 font-mono text-xs">{t("demoVars", { vars: connector.availability.missing_env.join(", ") })}</p>
            </Alert>
          ) : (
            <div className="flex flex-col gap-2 text-sm text-fg-muted">
              <p>{t("oauthIntro", { name: connector.name })}</p>
              {connector.oauth && connector.oauth.scopes.length > 0 ? (
                <div className="flex flex-col gap-1">
                  <span className="text-xs font-medium uppercase tracking-wide text-fg-subtle">{t("oauthScopes")}</span>
                  <div className="flex flex-wrap gap-1">
                    {connector.oauth.scopes.map((scope) => (
                      <Badge key={scope} tone="outline" className="font-mono">
                        {scope.replace("https://www.googleapis.com/auth/", "")}
                      </Badge>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          )
        ) : null}

        {agentCapable ? (
          <div className="flex flex-col gap-3 rounded-md border border-border p-3">
            {connector.auth_type !== "agent" ? (
              <label className="flex items-start justify-between gap-3 text-sm">
                <span>
                  <span className="font-medium text-fg">{t("useAgent")}</span>
                  <span className="block text-xs text-fg-muted">{t("useAgentHint")}</span>
                </span>
                <Switch checked={viaAgent} onCheckedChange={setViaAgent} aria-label={t("useAgent")} />
              </label>
            ) : null}
            {viaAgent ? (
              enrolledAgents.length === 0 && !agents.isLoading ? (
                <Alert
                  tone="warning"
                  action={
                    <Button asChild size="sm" variant="secondary">
                      <Link href="/app/connectors/agents">{t("manageAgents")}</Link>
                    </Button>
                  }
                >
                  {t("noAgents")}
                </Alert>
              ) : (
                <>
                  <Field label={t("agent")}>
                    <Select
                      value={agentId}
                      onValueChange={setAgentId}
                      placeholder={t("agentPlaceholder")}
                      options={enrolledAgents.map((a) => ({ value: a.id, label: a.name, description: a.hostname ?? undefined }))}
                    />
                  </Field>
                  {connector.category === "database" ? (
                    <Field label={t("agentSource")} htmlFor="agent-source">
                      {selectedAgent?.capabilities.sources?.length ? (
                        <Select
                          value={agentSource}
                          onValueChange={setAgentSource}
                          placeholder={t("agentSourcePlaceholder")}
                          options={selectedAgent.capabilities.sources
                            .filter((s) => s.type === connector.key)
                            .map((s) => ({ value: s.name, label: s.name, description: s.type }))}
                        />
                      ) : (
                        <Input
                          id="agent-source"
                          value={agentSource}
                          required
                          placeholder={t("agentSourcePlaceholder")}
                          onChange={(e) => setAgentSource(e.target.value)}
                        />
                      )}
                    </Field>
                  ) : null}
                </>
              )
            ) : null}
          </div>
        ) : null}

        {connector.category === "database" ? <Alert tone="info">{t("readOnlyNote")}</Alert> : null}

        {fields.map((field) => (
          <ConfigInput
            key={field.key}
            field={field}
            value={values[field.key] ?? ""}
            onChange={(v) => set(field.key, v)}
            pathOptions={connector.auth_type === "agent" ? (selectedAgent?.capabilities.paths ?? []) : []}
          />
        ))}
        {connector.docs_url ? (
          <a href={connector.docs_url} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-xs text-fg-muted hover:text-fg">
            <ExternalLink className="size-3" aria-hidden />
            {connector.docs_url}
          </a>
        ) : null}
      </form>
    </DialogContent>
  );
}

function ConfigInput({
  field,
  value,
  onChange,
  pathOptions,
}: {
  field: ConfigField;
  value: string | boolean;
  onChange: (value: string | boolean) => void;
  pathOptions: string[];
}) {
  const t = useTranslations("connectors.connect");
  const label = t.has(`fields.${field.key}`) ? t(`fields.${field.key}`) : field.key;
  const id = `field-${field.key}`;
  if (field.kind === "boolean") {
    return (
      <label className="flex items-start justify-between gap-3 text-sm">
        <span>
          <span className="font-medium text-fg">{field.key === "read_only" ? t("readOnly") : label}</span>
          {field.key === "read_only" ? <span className="block text-xs text-fg-muted">{t("readOnlyHint")}</span> : null}
        </span>
        <Switch checked={Boolean(value)} onCheckedChange={onChange} aria-label={label} />
      </label>
    );
  }
  if (field.kind === "select") {
    const options = field.options.map((o) => ({
      value: o,
      label:
        field.key === "verification"
          ? t(`verification.${o}`)
          : field.key === "transport"
            ? o === "stdio"
              ? t("transportStdio")
              : t("transportHttp")
            : o,
    }));
    return field.key === "transport" ? (
      <Field label={t("transport")}>
        <RadioCards className="grid-cols-2" value={String(value)} onValueChange={onChange} options={options} />
      </Field>
    ) : (
      <Field label={label}>
        <Select value={String(value)} onValueChange={onChange} options={options} aria-label={label} />
      </Field>
    );
  }
  if (field.kind === "json") {
    return (
      <Field label={label} htmlFor={id} hint={t("jsonHint", { example: '{"Authorization": "Bearer …"}' })}>
        <Textarea
          id={id}
          value={String(value)}
          rows={3}
          className="font-mono text-xs"
          spellCheck={false}
          onChange={(e) => onChange(e.target.value)}
        />
      </Field>
    );
  }
  if (field.key === "root" && pathOptions.length > 0) {
    return (
      <Field label={label}>
        <Select value={String(value)} onValueChange={onChange} options={pathOptions.map((p) => ({ value: p, label: p }))} />
      </Field>
    );
  }
  return (
    <Field label={label} htmlFor={id} hint={field.kind === "list" ? t("listHint") : undefined}>
      <Input
        id={id}
        type={field.kind === "secret" ? "password" : field.kind === "url" ? "url" : "text"}
        autoComplete="off"
        spellCheck={false}
        required={field.required}
        value={String(value)}
        placeholder={field.placeholder ?? undefined}
        className={field.kind === "secret" || field.kind === "url" ? "font-mono text-xs" : undefined}
        onChange={(e) => onChange(e.target.value)}
      />
    </Field>
  );
}
