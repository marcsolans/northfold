"use client";

import { Alert, Button, Dialog, DialogContent, Field, Input, RadioCards, Select, Skeleton, Switch } from "@messer/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import * as React from "react";

import { PlanLimitNotice, isPlanLimitError } from "@/components/billing";
import { http } from "@/lib/api";
import { errorMessage, useMembers } from "@/lib/studio/hooks";

import { CONFIG_FIELDS, channelKeys, useProviders } from "./hooks";
import { useProviderLabel } from "./provider-icon";
import type { ChannelCreated, ChannelEnvironment, ChannelProvider, ProviderInfo } from "./types";

interface FormState {
  provider: ChannelProvider;
  workforce: string;
  name: string;
  environment: ChannelEnvironment;
  locale: "es" | "en";
  demo: boolean;
  credentials: Record<string, string>;
  config: Record<string, string>;
  templateName: string;
  templateLanguage: string;
}

function initialState(provider: ChannelProvider, info: ProviderInfo | undefined, workforce: string): FormState {
  return {
    provider,
    workforce,
    name: "",
    environment: "production",
    locale: "es",
    demo: !(info?.platform_ready ?? false) && provider !== "email",
    credentials: {},
    config: {},
    templateName: "",
    templateLanguage: "es",
  };
}

export function ConnectChannelDialog({
  projectId,
  open,
  onOpenChange,
  onCreated,
}: {
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (channel: ChannelCreated) => void;
}) {
  const t = useTranslations("channels.connect");
  const tf = useTranslations("channels.fields");
  const tp = useTranslations("channels.providerHints");
  const te = useTranslations("channels.environments");
  const tc = useTranslations("common");
  const label = useProviderLabel();
  const qc = useQueryClient();
  const providers = useProviders();
  const agents = useMembers(projectId, "agent");
  const firstAgent = agents.data?.[0]?.name ?? "";
  const [form, setForm] = React.useState<FormState>(() => initialState("whatsapp", undefined, ""));
  const info = providers.data?.find((p) => p.provider === form.provider);

  React.useEffect(() => {
    if (open) setForm(initialState("whatsapp", providers.data?.find((p) => p.provider === "whatsapp"), firstAgent));
    // Reset only when the dialog opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  React.useEffect(() => {
    if (open && !form.workforce && firstAgent) setForm((f) => ({ ...f, workforce: firstAgent }));
  }, [open, firstAgent, form.workforce]);

  const pickProvider = (provider: string) => {
    const next = providers.data?.find((p) => p.provider === provider);
    setForm((f) => ({ ...initialState(provider as ChannelProvider, next, f.workforce), name: f.name, environment: f.environment, locale: f.locale }));
  };

  const create = useMutation({
    mutationFn: () => {
      const config: Record<string, unknown> = { locale: form.locale };
      for (const [k, v] of Object.entries(form.config)) if (v.trim()) config[k] = v.trim();
      if (form.provider === "whatsapp" && form.templateName.trim()) {
        config.template = { name: form.templateName.trim(), language: form.templateLanguage.trim() || "es" };
      }
      const credentials = form.demo
        ? {}
        : Object.fromEntries(Object.entries(form.credentials).filter(([, v]) => v.trim()).map(([k, v]) => [k, v.trim()]));
      return http.post<ChannelCreated>(`/projects/${projectId}/channels`, {
        provider: form.provider,
        workforce: form.workforce,
        name: form.name.trim(),
        environment: form.environment,
        demo: form.demo,
        credentials,
        config,
      });
    },
    onSuccess: (channel) => {
      void qc.invalidateQueries({ queryKey: channelKeys.list(projectId) });
      onOpenChange(false);
      onCreated(channel);
    },
  });

  const noAgents = agents.isSuccess && agents.data.length === 0;
  const missingRequired =
    !form.demo && info
      ? [
          ...info.credential_fields.filter((f) => f.required && !f.platform_available && !form.credentials[f.key]?.trim()),
          ...info.required_config.filter((f) => !f.platform_available && !form.config[f.key]?.trim()),
        ].map((f) => f.key)
      : [];
  const configFields = CONFIG_FIELDS[form.provider] ?? [];

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.workforce || missingRequired.length) return;
    create.mutate();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={t("title")} description={t("description")} wide>
        {providers.isLoading || agents.isLoading ? (
          <div className="flex flex-col gap-3">
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-8 w-full" />
          </div>
        ) : providers.error || agents.error ? (
          <Alert tone="danger">{tc("errorGeneric")}</Alert>
        ) : noAgents ? (
          <Alert tone="warning" title={t("noAgentsTitle")}>
            {t("noAgentsBody")}
          </Alert>
        ) : (
          <form id="connect-channel" onSubmit={submit} className="flex flex-col gap-4" noValidate>
            <Field label={t("provider")}>
              <RadioCards
                value={form.provider}
                onValueChange={pickProvider}
                className="grid-cols-1 sm:grid-cols-2 lg:grid-cols-3"
                options={(providers.data ?? []).map((p) => ({ value: p.provider, label: label(p.provider), description: tp(p.provider) }))}
              />
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t("agent")} htmlFor="ch-agent" hint={t("agentHint")}>
                <Select
                  id="ch-agent"
                  aria-label={t("agent")}
                  value={form.workforce || undefined}
                  onValueChange={(v) => setForm((f) => ({ ...f, workforce: v }))}
                  options={(agents.data ?? []).map((a) => ({ value: a.name, label: a.name }))}
                />
              </Field>
              <Field label={t("name")} htmlFor="ch-name" hint={tc("optional")}>
                <Input
                  id="ch-name"
                  value={form.name}
                  maxLength={200}
                  placeholder={`${label(form.provider)} · ${form.workforce}`}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                />
              </Field>
              <Field label={t("environment")} htmlFor="ch-env" hint={t("environmentHint")}>
                <Select
                  id="ch-env"
                  aria-label={t("environment")}
                  value={form.environment}
                  onValueChange={(v) => setForm((f) => ({ ...f, environment: v as ChannelEnvironment }))}
                  options={[
                    { value: "production", label: te("production") },
                    { value: "development", label: te("development") },
                  ]}
                />
              </Field>
              <Field label={t("locale")} htmlFor="ch-locale" hint={t("localeHint")}>
                <Select
                  id="ch-locale"
                  aria-label={t("locale")}
                  value={form.locale}
                  onValueChange={(v) => setForm((f) => ({ ...f, locale: v as "es" | "en" }))}
                  options={[
                    { value: "es", label: t("locales.es") },
                    { value: "en", label: t("locales.en") },
                  ]}
                />
              </Field>
            </div>

            <div className="flex items-start justify-between gap-4 rounded-md border border-border px-3 py-2.5">
              <div>
                <label htmlFor="ch-demo" className="text-sm font-medium">
                  {t("demo")}
                </label>
                <p className="text-xs text-fg-muted">{form.demo ? t("demoOn") : t("demoOff")}</p>
              </div>
              <Switch id="ch-demo" checked={form.demo} onCheckedChange={(v) => setForm((f) => ({ ...f, demo: v }))} />
            </div>

            {!form.demo && info ? (
              <div className="grid gap-3 sm:grid-cols-2">
                {info.credential_fields.map((f) => (
                  <Field
                    key={f.key}
                    label={tf(f.key)}
                    htmlFor={`cred-${f.key}`}
                    hint={f.platform_available ? t("platformValue") : f.required ? tc("required") : tc("optional")}
                  >
                    <Input
                      id={`cred-${f.key}`}
                      type={f.secret ? "password" : "text"}
                      autoComplete="off"
                      spellCheck={false}
                      className="font-mono"
                      value={form.credentials[f.key] ?? ""}
                      onChange={(e) => setForm((s) => ({ ...s, credentials: { ...s.credentials, [f.key]: e.target.value } }))}
                    />
                  </Field>
                ))}
                {configFields.map((key) => {
                  const platform = info.required_config.find((r) => r.key === key)?.platform_available;
                  const required = info.required_config.some((r) => r.key === key);
                  return (
                    <Field
                      key={key}
                      label={tf(key)}
                      htmlFor={`cfg-${key}`}
                      hint={platform ? t("platformValue") : required ? tc("required") : tc("optional")}
                    >
                      <Input
                        id={`cfg-${key}`}
                        autoComplete="off"
                        spellCheck={false}
                        className="font-mono"
                        value={form.config[key] ?? ""}
                        onChange={(e) => setForm((s) => ({ ...s, config: { ...s.config, [key]: e.target.value } }))}
                      />
                    </Field>
                  );
                })}
                {form.provider === "whatsapp" ? (
                  <>
                    <Field label={tf("template_name")} htmlFor="cfg-tpl" hint={t("templateHint")}>
                      <Input
                        id="cfg-tpl"
                        className="font-mono"
                        placeholder="respuesta_pendiente"
                        value={form.templateName}
                        onChange={(e) => setForm((s) => ({ ...s, templateName: e.target.value }))}
                      />
                    </Field>
                    <Field label={tf("template_language")} htmlFor="cfg-tpl-lang">
                      <Input
                        id="cfg-tpl-lang"
                        className="font-mono"
                        value={form.templateLanguage}
                        onChange={(e) => setForm((s) => ({ ...s, templateLanguage: e.target.value }))}
                      />
                    </Field>
                  </>
                ) : null}
              </div>
            ) : null}
            {missingRequired.length ? (
              <p className="text-xs text-fg-muted">{t("missing", { fields: missingRequired.map((k) => tf(k)).join(", ") })}</p>
            ) : null}
            {create.error && isPlanLimitError(create.error) ? <PlanLimitNotice error={create.error} /> : null}
            {create.error && !isPlanLimitError(create.error) ? (
              <Alert tone="danger">{errorMessage(create.error, tc("errorGeneric"))}</Alert>
            ) : null}
          </form>
        )}
        <div className="mt-5 flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
            {tc("cancel")}
          </Button>
          <Button
            type="submit"
            form="connect-channel"
            variant="primary"
            loading={create.isPending}
            disabled={noAgents || !form.workforce || missingRequired.length > 0}
          >
            {t("submit")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
