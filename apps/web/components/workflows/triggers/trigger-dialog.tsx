"use client";

import { Alert, Button, CodeBlock, CopyButton, Dialog, DialogContent, Field, Input, Select, Switch, Textarea, toast } from "@messer/ui";
import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";
import { errorMessage } from "@/lib/studio/hooks";
import { TRIGGER_KINDS, type Palette, type Trigger, type TriggerKind } from "@/lib/workflows/types";

import { CronPicker } from "./cron-picker";

export function curlExample(url: string, comments: { secret: string; body: string }): string {
  return [
    `SECRET='whsec_…'   # ${comments.secret}`,
    `BODY='{"ejemplo": true}'   # ${comments.body}`,
    "TS=$(date +%s)",
    `SIG=$(printf '%s.%s' "$TS" "$BODY" | openssl dgst -sha256 -hmac "$SECRET" -hex | sed 's/^.* //')`,
    `curl -X POST '${url}' \\`,
    "  -H 'Content-Type: application/json' \\",
    '  -H "X-Messer-Signature: t=$TS,v1=$SIG" \\',
    "  -H 'X-Messer-Event-Id: evento-1' \\",
    '  -d "$BODY"',
  ].join("\n");
}

/** The webhook secret is only returned when the trigger is created or the secret is rotated. */
export function SecretDialog({ trigger, onClose }: { trigger: Trigger | null; onClose: () => void }) {
  const t = useTranslations("workflows.triggers");
  const tc = useTranslations("common");
  return (
    <Dialog open={trigger !== null} onOpenChange={(open) => (!open ? onClose() : undefined)}>
      <DialogContent
        wide
        title={t("secretTitle")}
        description={t("secretDescription")}
        footer={
          <Button variant="primary" onClick={onClose}>
            {t("secretDone")}
          </Button>
        }
      >
        {trigger ? (
          <div className="space-y-3">
            <Field label={t("webhookUrl")}>
              <div className="flex items-center gap-2">
                <code className="min-w-0 flex-1 truncate rounded-md border border-border bg-subtle px-2 py-1.5 font-mono text-xs">{trigger.webhook_url}</code>
                <CopyButton value={trigger.webhook_url ?? ""} label={tc("copy")} />
              </div>
            </Field>
            <Field label={t("secret")}>
              <div className="flex items-center gap-2">
                <code className="min-w-0 flex-1 truncate rounded-md border border-border bg-subtle px-2 py-1.5 font-mono text-xs" data-testid="webhook-secret">
                  {trigger.secret}
                </code>
                <CopyButton value={trigger.secret ?? ""} label={tc("copy")} />
              </div>
            </Field>
            <Alert tone="warning">{t("secretOnce")}</Alert>
            <p className="text-xs text-fg-muted">{t("signatureRecipe")}</p>
            <CodeBlock code={curlExample(trigger.webhook_url ?? "", { secret: t("curlSecret"), body: t("curlBody") })} language="bash" />
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

interface Draft {
  kind: TriggerKind;
  name: string;
  environment: "development" | "production";
  enabled: boolean;
  staticInput: string;
  expression: string;
  timezone: string;
  cronValid: boolean;
  kbId: string;
  connectionId: string;
  event: string;
}

function draftFrom(trigger: Trigger | null): Draft {
  const cfg = trigger?.config ?? {};
  return {
    kind: trigger?.kind ?? "webhook",
    name: trigger?.name ?? "",
    environment: trigger?.environment ?? "development",
    enabled: trigger?.enabled ?? true,
    staticInput: JSON.stringify(cfg.static_input ?? {}, null, 2),
    expression: typeof cfg.expression === "string" ? cfg.expression : "0 9 * * 1-5",
    timezone: typeof cfg.timezone === "string" ? cfg.timezone : "Europe/Madrid",
    cronValid: true,
    kbId: typeof cfg.kb_id === "string" ? cfg.kb_id : "",
    connectionId: typeof cfg.connection_id === "string" ? cfg.connection_id : "",
    event: typeof cfg.event === "string" ? cfg.event : "",
  };
}

/** Create or edit a trigger of this workflow. */
export function TriggerDialog({
  projectId,
  workflow,
  palette,
  open,
  trigger,
  onClose,
  onSaved,
}: {
  projectId: string;
  workflow: string;
  palette: Palette | undefined;
  open: boolean;
  trigger: Trigger | null;
  onClose: () => void;
  onSaved: (trigger: Trigger, created: boolean) => void;
}) {
  const t = useTranslations("workflows.triggers");
  const tc = useTranslations("common");
  const [draft, setDraft] = React.useState<Draft>(() => draftFrom(trigger));
  React.useEffect(() => {
    if (open) setDraft(draftFrom(trigger));
  }, [open, trigger]);
  const patch = (update: Partial<Draft>) => setDraft((d) => ({ ...d, ...update }));

  let staticInput: Record<string, unknown> | null = null;
  try {
    const raw: unknown = JSON.parse(draft.staticInput || "{}");
    staticInput = raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as Record<string, unknown>) : null;
  } catch {
    staticInput = null;
  }
  const kindInvalid =
    (draft.kind === "cron" && !draft.cronValid) ||
    (draft.kind === "file" && !draft.kbId) ||
    (draft.kind === "connector_event" && (!draft.connectionId || !draft.event.trim()));
  const invalid = staticInput === null || kindInvalid;

  const save = useMutation({
    mutationFn: async () => {
      const config: Record<string, unknown> = { static_input: staticInput ?? {} };
      if (draft.kind === "cron") Object.assign(config, { expression: draft.expression, timezone: draft.timezone });
      if (draft.kind === "file") config.kb_id = draft.kbId;
      if (draft.kind === "connector_event") Object.assign(config, { connection_id: draft.connectionId, event: draft.event.trim() });
      if (trigger) {
        return http.patch<Trigger>(`/triggers/${trigger.id}`, {
          name: draft.name,
          config,
          environment: draft.environment,
          enabled: draft.enabled,
        });
      }
      return http.post<Trigger>(`/projects/${projectId}/triggers`, {
        workforce: workflow,
        kind: draft.kind,
        name: draft.name,
        config,
        environment: draft.environment,
        enabled: draft.enabled,
      });
    },
    onSuccess: (saved) => onSaved(saved, trigger === null),
    onError: (err) => toast.error(errorMessage(err, tc("errorGeneric"))),
  });

  return (
    <Dialog open={open} onOpenChange={(o) => (!o ? onClose() : undefined)}>
      <DialogContent
        wide
        title={trigger ? t("editTitle") : t("newTitle")}
        description={t("dialogDescription")}
        footer={
          <>
            <Button variant="ghost" onClick={onClose}>
              {tc("cancel")}
            </Button>
            <Button variant="primary" loading={save.isPending} disabled={invalid} onClick={() => save.mutate()}>
              {trigger ? tc("save") : tc("create")}
            </Button>
          </>
        }
      >
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-3">
            <Field label={t("kind")} htmlFor="trigger-kind">
              <Select
                id="trigger-kind"
                value={draft.kind}
                disabled={trigger !== null}
                onValueChange={(v) => patch({ kind: v as TriggerKind })}
                options={TRIGGER_KINDS.map((k) => ({ value: k, label: t(`kinds.${k}.label`), description: t(`kinds.${k}.description`) }))}
              />
            </Field>
            <Field label={tc("name")} htmlFor="trigger-name" hint={t("nameHint")}>
              <Input id="trigger-name" value={draft.name} maxLength={120} onChange={(e) => patch({ name: e.target.value })} />
            </Field>
            <Field label={t("environment")} htmlFor="trigger-environment" hint={t("environmentHint")}>
              <Select
                id="trigger-environment"
                value={draft.environment}
                onValueChange={(v) => patch({ environment: v as Draft["environment"] })}
                options={[
                  { value: "development", label: t("environments.development") },
                  { value: "production", label: t("environments.production") },
                ]}
              />
            </Field>
            <label className="flex items-center justify-between gap-2 text-sm">
              {t("enabled")}
              <Switch checked={draft.enabled} onCheckedChange={(v) => patch({ enabled: v })} aria-label={t("enabled")} />
            </label>
          </div>
          <div className="space-y-3">
            {draft.kind === "cron" ? (
              <CronPicker
                expression={draft.expression}
                timezone={draft.timezone}
                onChange={({ expression, timezone, valid }) => patch({ expression, timezone, cronValid: valid })}
              />
            ) : null}
            {draft.kind === "webhook" ? <Alert tone="info">{t("webhookHint")}</Alert> : null}
            {draft.kind === "email" ? <Alert tone="info">{t("emailHint")}</Alert> : null}
            {draft.kind === "manual" ? <Alert tone="info">{t("manualHint")}</Alert> : null}
            {draft.kind === "file" ? (
              <Field label={t("knowledgeBase")} htmlFor="trigger-kb" hint={t("fileHint")}>
                {palette?.knowledge_bases.length ? (
                  <Select
                    id="trigger-kb"
                    value={draft.kbId || undefined}
                    placeholder={t("chooseKnowledgeBase")}
                    onValueChange={(v) => patch({ kbId: v })}
                    options={palette.knowledge_bases.map((kb) => ({ value: kb.id, label: kb.name }))}
                  />
                ) : (
                  <Alert tone="info">{t("noKnowledgeBases")}</Alert>
                )}
              </Field>
            ) : null}
            {draft.kind === "connector_event" ? (
              <>
                <Field label={t("connection")} htmlFor="trigger-connection">
                  {palette?.connections.length ? (
                    <Select
                      id="trigger-connection"
                      value={draft.connectionId || undefined}
                      placeholder={t("chooseConnection")}
                      onValueChange={(v) => patch({ connectionId: v })}
                      options={palette.connections.map((c) => ({ value: c.id, label: c.name, description: c.connector_name }))}
                    />
                  ) : (
                    <Alert tone="info">{t("noConnections")}</Alert>
                  )}
                </Field>
                <Field label={t("event")} htmlFor="trigger-event" hint={t("eventHint")}>
                  <Input id="trigger-event" value={draft.event} className="font-mono text-xs" placeholder="gmail.new_email" onChange={(e) => patch({ event: e.target.value })} />
                </Field>
              </>
            ) : null}
            <Field label={t("staticInput")} htmlFor="trigger-static" hint={t("staticInputHint")} error={staticInput === null ? t("invalidJson") : undefined}>
              <Textarea id="trigger-static" rows={4} className="font-mono text-xs" value={draft.staticInput} onChange={(e) => patch({ staticInput: e.target.value })} />
            </Field>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
