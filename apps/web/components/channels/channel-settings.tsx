"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  ConfirmDialog,
  Field,
  Input,
  Select,
  Switch,
  Textarea,
  toast,
} from "@messer/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Pause, Play, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";
import { errorMessage, useMembers } from "@/lib/studio/hooks";

import { SetupDialog } from "./channels-page";
import { CONFIG_FIELDS, channelKeys, useProviders } from "./hooks";
import type { Channel, ChannelEnvironment, SecretRotated } from "./types";

function str(value: unknown): string {
  return typeof value === "string" ? value : typeof value === "number" ? String(value) : "";
}

function templateOf(config: Record<string, unknown>): { name: string; language: string } {
  const tpl = config.template;
  if (tpl && typeof tpl === "object") {
    const rec = tpl as Record<string, unknown>;
    return { name: str(rec.name), language: str(rec.language) || "es" };
  }
  return { name: "", language: "es" };
}

export function ChannelSettings({ channel, projectId, canBuild }: { channel: Channel; projectId: string; canBuild: boolean }) {
  const t = useTranslations("channels.settings");
  const tf = useTranslations("channels.fields");
  const te = useTranslations("channels.environments");
  const tconn = useTranslations("channels.connect");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const router = useRouter();
  const agents = useMembers(projectId, "agent");
  const providers = useProviders();
  const info = providers.data?.find((p) => p.provider === channel.provider);
  const cfg = channel.config;

  const [name, setName] = React.useState(channel.name);
  const [workforce, setWorkforce] = React.useState(channel.workforce_name ?? "");
  const [environment, setEnvironment] = React.useState<ChannelEnvironment>(channel.environment);
  const [locale, setLocale] = React.useState(str(cfg.locale) || "es");
  const [approvalMessage, setApprovalMessage] = React.useState(str(cfg.approval_message));
  const [errorText, setErrorText] = React.useState(str(cfg.error_message));
  const [config, setConfig] = React.useState<Record<string, string>>(() =>
    Object.fromEntries((CONFIG_FIELDS[channel.provider] ?? []).map((k) => [k, str(cfg[k])])),
  );
  const [template, setTemplate] = React.useState(() => templateOf(cfg));
  const [groupMode, setGroupMode] = React.useState(str(cfg.group_mode) || "mention");
  const [credentials, setCredentials] = React.useState<Record<string, string>>({});
  const [demo, setDemo] = React.useState(channel.demo);
  const [confirmDelete, setConfirmDelete] = React.useState(false);
  const [confirmRotate, setConfirmRotate] = React.useState(false);
  const [rotated, setRotated] = React.useState<string | null>(null);

  const refresh = (updated: Channel) => {
    qc.setQueryData(channelKeys.detail(channel.id), updated);
    void qc.invalidateQueries({ queryKey: channelKeys.list(projectId) });
  };

  const save = useMutation({
    mutationFn: () => {
      const nextConfig: Record<string, unknown> = {
        locale,
        approval_message: approvalMessage.trim() || null,
        error_message: errorText.trim() || null,
      };
      for (const [k, v] of Object.entries(config)) nextConfig[k] = v.trim() || null;
      if (channel.provider === "whatsapp") {
        nextConfig.template = template.name.trim() ? { name: template.name.trim(), language: template.language.trim() || "es" } : null;
      }
      if (channel.provider === "telegram") nextConfig.group_mode = groupMode;
      const creds = Object.fromEntries(Object.entries(credentials).filter(([, v]) => v.trim()).map(([k, v]) => [k, v.trim()]));
      return http.patch<Channel>(`/channels/${channel.id}`, {
        name: name.trim() || null,
        workforce: workforce || null,
        environment,
        config: nextConfig,
        demo,
        ...(Object.keys(creds).length ? { credentials: creds } : {}),
      });
    },
    onSuccess: (updated) => {
      refresh(updated);
      setCredentials({});
      toast.success(updated.status === "error" && updated.error ? t("savedWithError") : t("saved"));
    },
  });

  const toggle = useMutation({
    mutationFn: (enabled: boolean) => http.patch<Channel>(`/channels/${channel.id}`, { enabled }),
    onSuccess: (updated) => {
      refresh(updated);
      toast.success(updated.status === "disabled" ? t("paused") : t("resumed"));
    },
    onError: (err) => toast.error(errorMessage(err, tc("errorGeneric"))),
  });

  const rotate = useMutation({
    mutationFn: () => http.post<SecretRotated>(`/channels/${channel.id}/rotate-secret`),
    onSuccess: (res) => {
      setConfirmRotate(false);
      setRotated(res.webhook_secret);
      void qc.invalidateQueries({ queryKey: channelKeys.detail(channel.id) });
    },
    onError: (err) => toast.error(errorMessage(err, tc("errorGeneric"))),
  });

  const remove = useMutation({
    mutationFn: () => http.del(`/channels/${channel.id}`),
    onSuccess: () => {
      setConfirmDelete(false);
      toast.success(t("disconnected", { name: channel.name }));
      void qc.invalidateQueries({ queryKey: channelKeys.list(projectId) });
      router.push(`/app/projects/${projectId}/channels`);
    },
    onError: (err) => toast.error(errorMessage(err, tc("errorGeneric"))),
  });

  if (!channel.supported) {
    return <Alert tone="info">{t("unsupported")}</Alert>;
  }
  const readOnly = !canBuild;
  const enabled = channel.status !== "disabled";

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader title={t("generalTitle")} description={t("generalDescription")} />
        <CardBody>
          <form
            id="channel-settings"
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (!readOnly) save.mutate();
            }}
          >
            <fieldset disabled={readOnly} className="grid gap-3 sm:grid-cols-2">
              <Field label={tconn("name")} htmlFor="set-name">
                <Input id="set-name" value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />
              </Field>
              <Field label={tconn("agent")} htmlFor="set-agent">
                <Select
                  id="set-agent"
                  aria-label={tconn("agent")}
                  value={workforce || undefined}
                  disabled={readOnly}
                  onValueChange={setWorkforce}
                  options={(agents.data ?? []).map((a) => ({ value: a.name, label: a.name }))}
                />
              </Field>
              <Field label={tconn("environment")} htmlFor="set-env" hint={tconn("environmentHint")}>
                <Select
                  id="set-env"
                  aria-label={tconn("environment")}
                  value={environment}
                  disabled={readOnly}
                  onValueChange={(v) => setEnvironment(v as ChannelEnvironment)}
                  options={[
                    { value: "production", label: te("production") },
                    { value: "development", label: te("development") },
                  ]}
                />
              </Field>
              <Field label={tconn("locale")} htmlFor="set-locale" hint={tconn("localeHint")}>
                <Select
                  id="set-locale"
                  aria-label={tconn("locale")}
                  value={locale}
                  disabled={readOnly}
                  onValueChange={setLocale}
                  options={[
                    { value: "es", label: tconn("locales.es") },
                    { value: "en", label: tconn("locales.en") },
                  ]}
                />
              </Field>
              <Field label={t("approvalMessage")} htmlFor="set-approval" hint={t("defaultHint")} className="sm:col-span-2">
                <Textarea id="set-approval" rows={2} maxLength={1000} value={approvalMessage} onChange={(e) => setApprovalMessage(e.target.value)} />
              </Field>
              <Field label={t("errorMessage")} htmlFor="set-error" hint={t("defaultHint")} className="sm:col-span-2">
                <Textarea id="set-error" rows={2} maxLength={1000} value={errorText} onChange={(e) => setErrorText(e.target.value)} />
              </Field>
              {(CONFIG_FIELDS[channel.provider] ?? []).map((key) => (
                <Field key={key} label={tf(key)} htmlFor={`set-${key}`}>
                  <Input
                    id={`set-${key}`}
                    className="font-mono"
                    value={config[key] ?? ""}
                    onChange={(e) => setConfig((c) => ({ ...c, [key]: e.target.value }))}
                  />
                </Field>
              ))}
              {channel.provider === "whatsapp" ? (
                <>
                  <Field label={tf("template_name")} htmlFor="set-tpl" hint={tconn("templateHint")}>
                    <Input
                      id="set-tpl"
                      className="font-mono"
                      value={template.name}
                      onChange={(e) => setTemplate((tpl) => ({ ...tpl, name: e.target.value }))}
                    />
                  </Field>
                  <Field label={tf("template_language")} htmlFor="set-tpl-lang">
                    <Input
                      id="set-tpl-lang"
                      className="font-mono"
                      value={template.language}
                      onChange={(e) => setTemplate((tpl) => ({ ...tpl, language: e.target.value }))}
                    />
                  </Field>
                </>
              ) : null}
              {channel.provider === "telegram" ? (
                <Field label={tf("group_mode")} htmlFor="set-group">
                  <Select
                    id="set-group"
                    aria-label={tf("group_mode")}
                    value={groupMode}
                    disabled={readOnly}
                    onValueChange={setGroupMode}
                    options={[
                      { value: "mention", label: t("groupModes.mention") },
                      { value: "all", label: t("groupModes.all") },
                    ]}
                  />
                </Field>
              ) : null}
            </fieldset>

            {info && info.credential_fields.length ? (
              <fieldset disabled={readOnly} className="flex flex-col gap-3 border-t border-border pt-4">
                <legend className="sr-only">{t("credentialsTitle")}</legend>
                <div>
                  <p className="text-sm font-medium">{t("credentialsTitle")}</p>
                  <p className="text-xs text-fg-muted">{t("credentialsDescription")}</p>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  {info.credential_fields.map((f) => {
                    const isSet = channel.credentials_set.includes(f.key);
                    return (
                      <Field
                        key={f.key}
                        label={
                          <span className="flex items-center gap-1.5">
                            {tf(f.key)}
                            {isSet ? <Badge tone="success">{t("credentialSet")}</Badge> : f.platform_available ? <Badge tone="outline">{t("credentialPlatform")}</Badge> : null}
                          </span>
                        }
                        htmlFor={`set-cred-${f.key}`}
                      >
                        <Input
                          id={`set-cred-${f.key}`}
                          type={f.secret ? "password" : "text"}
                          autoComplete="off"
                          className="font-mono"
                          placeholder={isSet ? t("keepValue") : ""}
                          value={credentials[f.key] ?? ""}
                          onChange={(e) => setCredentials((c) => ({ ...c, [f.key]: e.target.value }))}
                        />
                      </Field>
                    );
                  })}
                </div>
              </fieldset>
            ) : null}

            <div className="flex items-start justify-between gap-4 rounded-md border border-border px-3 py-2.5">
              <div>
                <label htmlFor="set-demo" className="text-sm font-medium">
                  {tconn("demo")}
                </label>
                <p className="text-xs text-fg-muted">{demo ? tconn("demoOn") : tconn("demoOff")}</p>
                {!demo && channel.demo && channel.missing_credentials.length ? (
                  <p className="mt-1 text-xs text-warning">
                    {tconn("missing", { fields: channel.missing_credentials.map((k) => (tf.has(k) ? tf(k) : k)).join(", ") })}
                  </p>
                ) : null}
              </div>
              <Switch id="set-demo" checked={demo} disabled={readOnly} onCheckedChange={setDemo} />
            </div>
            {save.error ? <Alert tone="danger">{errorMessage(save.error, tc("errorGeneric"))}</Alert> : null}
            {canBuild ? (
              <div className="flex justify-end">
                <Button type="submit" variant="primary" loading={save.isPending}>
                  {tc("save")}
                </Button>
              </div>
            ) : null}
          </form>
        </CardBody>
      </Card>

      {canBuild ? (
        <Card>
          <CardHeader title={t("dangerTitle")} description={t("dangerDescription")} />
          <CardBody className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-sm font-medium">{enabled ? t("pauseTitle") : t("resumeTitle")}</p>
                <p className="text-xs text-fg-muted">{enabled ? t("pauseDescription") : t("resumeDescription")}</p>
              </div>
              <Button variant="secondary" loading={toggle.isPending} onClick={() => toggle.mutate(!enabled)}>
                {enabled ? <Pause /> : <Play />}
                {enabled ? t("pause") : t("resume")}
              </Button>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3">
              <div>
                <p className="text-sm font-medium">{t("rotateTitle")}</p>
                <p className="text-xs text-fg-muted">{t("rotateDescription")}</p>
              </div>
              <Button variant="secondary" onClick={() => setConfirmRotate(true)}>
                <KeyRound />
                {t("rotate")}
              </Button>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3">
              <div>
                <p className="text-sm font-medium">{t("disconnectTitle")}</p>
                <p className="text-xs text-fg-muted">{t("disconnectDescription")}</p>
              </div>
              <Button variant="danger" onClick={() => setConfirmDelete(true)}>
                <Trash2 />
                {t("disconnect")}
              </Button>
            </div>
          </CardBody>
        </Card>
      ) : null}

      <ConfirmDialog
        open={confirmRotate}
        onOpenChange={setConfirmRotate}
        title={t("rotateConfirmTitle")}
        description={t("rotateConfirmBody")}
        confirmLabel={t("rotate")}
        cancelLabel={tc("cancel")}
        loading={rotate.isPending}
        onConfirm={() => rotate.mutate()}
      />
      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title={t("disconnectConfirmTitle", { name: channel.name })}
        description={t("disconnectConfirmBody")}
        confirmLabel={t("disconnect")}
        cancelLabel={tc("cancel")}
        loading={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
      <SetupDialog channel={rotated ? channel : null} secret={rotated} onClose={() => setRotated(null)} />
    </div>
  );
}
