"use client";

import {
  Badge,
  Button,
  Card,
  CodeBlock,
  ConfirmDialog,
  CopyButton,
  Dialog,
  DialogContent,
  EmptyState,
  ErrorState,
  Field,
  Input,
  SkeletonRows,
  Switch,
  Textarea,
  toast,
} from "@messer/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  CalendarClock,
  ChevronDown,
  ChevronRight,
  FileUp,
  Hand,
  KeyRound,
  Mail,
  Pencil,
  Play,
  Plug,
  Plus,
  Send,
  Trash2,
  Webhook,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { RunStatusBadge } from "@/components/traces/run-status-badge";
import { http } from "@/lib/api";
import { formatDate, formatRelative, localeTag } from "@/lib/format";
import { errorMessage } from "@/lib/studio/hooks";
import { useTriggers, workflowKeys } from "@/lib/workflows/hooks";
import type { Palette, Trigger, TriggerKind } from "@/lib/workflows/types";

import { SecretDialog, TriggerDialog, curlExample } from "./trigger-dialog";

const KIND_ICONS: Record<TriggerKind, typeof Zap> = {
  manual: Hand,
  cron: CalendarClock,
  webhook: Webhook,
  email: Mail,
  file: FileUp,
  connector_event: Plug,
};

/** Every way this workflow starts on its own: schedules, webhooks, inbound email, files and connector events. */
export function TriggersTab({
  projectId,
  workflowId,
  workflow,
  palette,
  canBuild,
}: {
  projectId: string;
  workflowId: string;
  workflow: string;
  palette: Palette | undefined;
  canBuild: boolean;
}) {
  const t = useTranslations("workflows.triggers");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const triggers = useTriggers(projectId);
  const [editing, setEditing] = React.useState<Trigger | null>(null);
  const [creating, setCreating] = React.useState(false);
  const [secret, setSecret] = React.useState<Trigger | null>(null);
  const [deleting, setDeleting] = React.useState<Trigger | null>(null);
  const [rotating, setRotating] = React.useState<Trigger | null>(null);
  const [emailing, setEmailing] = React.useState<Trigger | null>(null);
  const [expanded, setExpanded] = React.useState<string | null>(null);
  const [email, setEmail] = React.useState({ from: "cliente@example.com", subject: "", text: "" });
  const mine = (triggers.data ?? []).filter((tr) => tr.workforce_id === workflowId);
  const refresh = () => void qc.invalidateQueries({ queryKey: workflowKeys.triggers(projectId) });
  const kbName = (id: unknown) => palette?.knowledge_bases.find((kb) => kb.id === id)?.name ?? String(id ?? "");
  const connectionName = (id: unknown) => palette?.connections.find((c) => c.id === id)?.name ?? String(id ?? "");

  const toggle = useMutation({
    mutationFn: (tr: Trigger) => http.patch<Trigger>(`/triggers/${tr.id}`, { enabled: !tr.enabled }),
    onSuccess: (tr) => {
      refresh();
      toast.success(tr.enabled ? t("enabledToast") : t("disabledToast"));
    },
    onError: (err) => toast.error(errorMessage(err, tc("errorGeneric"))),
  });
  const fire = useMutation({
    mutationFn: (tr: Trigger) => http.post<{ accepted: boolean }>(`/triggers/${tr.id}/fire`, { payload: {} }),
    onSuccess: () => {
      toast.success(t("fired"));
      window.setTimeout(refresh, 3000);
    },
    onError: (err) => toast.error(errorMessage(err, tc("errorGeneric"))),
  });
  const remove = useMutation({
    mutationFn: (tr: Trigger) => http.del(`/triggers/${tr.id}`),
    onSuccess: () => {
      setDeleting(null);
      refresh();
      toast.success(t("deleted"));
    },
    onError: (err) => toast.error(errorMessage(err, tc("errorGeneric"))),
  });
  const rotate = useMutation({
    mutationFn: (tr: Trigger) => http.post<Trigger>(`/triggers/${tr.id}/rotate-secret`),
    onSuccess: (tr) => {
      setRotating(null);
      setSecret(tr);
      refresh();
    },
    onError: (err) => toast.error(errorMessage(err, tc("errorGeneric"))),
  });
  const simulate = useMutation({
    mutationFn: (tr: Trigger) => http.post<{ fired: number }>(`/triggers/${tr.id}/simulate-email`, email),
    onSuccess: (res) => {
      setEmailing(null);
      toast.success(res.fired ? t("emailSent") : t("emailNotRouted"));
      window.setTimeout(refresh, 3000);
    },
    onError: (err) => toast.error(errorMessage(err, tc("errorGeneric"))),
  });

  const newButton = canBuild ? (
    <Button variant="primary" size="sm" onClick={() => setCreating(true)}>
      <Plus />
      {t("new")}
    </Button>
  ) : null;

  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-4 md:px-5">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">{t("title")}</h2>
          <p className="text-sm text-fg-muted">{t("description")}</p>
        </div>
        {newButton}
      </div>
      {triggers.isLoading ? (
        <SkeletonRows rows={3} />
      ) : triggers.error ? (
        <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void triggers.refetch()} retryLabel={tc("retry")} />
      ) : mine.length === 0 ? (
        <EmptyState icon={<Zap />} title={t("empty.title")} description={t("empty.description")} action={newButton} />
      ) : (
        <ul className="space-y-3">
          {mine.map((tr) => {
            const Icon = KIND_ICONS[tr.kind] ?? Zap;
            const history = tr.state?.history ?? [];
            const open = expanded === tr.id;
            return (
              <li key={tr.id}>
                <Card className="p-3">
                  <div className="flex flex-wrap items-start gap-3">
                    <span className="flex size-8 shrink-0 items-center justify-center rounded-md border border-border bg-subtle" aria-hidden>
                      <Icon className="size-4 text-fg-muted" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="flex flex-wrap items-center gap-2 text-sm font-semibold">
                        {tr.name}
                        <Badge tone="outline">{t(`kinds.${tr.kind}.label`)}</Badge>
                        <Badge tone={tr.environment === "production" ? "accent" : "neutral"}>{t(`environments.${tr.environment}`)}</Badge>
                        {!tr.enabled ? <Badge tone="warning">{t("disabled")}</Badge> : null}
                      </p>
                      <div className="mt-1 space-y-1 text-xs text-fg-muted">
                        {tr.kind === "cron" ? (
                          <p>
                            <code className="font-mono">{String(tr.config.expression ?? "")}</code> · {String(tr.config.timezone ?? "")}
                            {tr.next_fire_at ? ` · ${t("nextRun", { when: formatDate(tr.next_fire_at, locale, true) })}` : ""}
                          </p>
                        ) : null}
                        {tr.kind === "webhook" && tr.webhook_url ? (
                          <p className="flex items-center gap-1">
                            <code className="truncate font-mono" data-testid="webhook-url">{tr.webhook_url}</code>
                            <CopyButton value={tr.webhook_url} label={tc("copy")} />
                          </p>
                        ) : null}
                        {tr.kind === "email" && tr.inbound_address ? (
                          <p className="flex items-center gap-1">
                            <code className="truncate font-mono">{tr.inbound_address}</code>
                            <CopyButton value={tr.inbound_address} label={tc("copy")} />
                          </p>
                        ) : null}
                        {tr.kind === "file" ? <p>{t("fileOn", { kb: kbName(tr.config.kb_id) })}</p> : null}
                        {tr.kind === "connector_event" ? (
                          <p>{t("eventOn", { event: String(tr.config.event ?? ""), connection: connectionName(tr.config.connection_id) })}</p>
                        ) : null}
                        <p>
                          {tr.last_fired_at ? t("lastFired", { when: formatRelative(tr.last_fired_at, locale) }) : t("neverFired")}
                          {tr.state?.consecutive_failures ? ` · ${t("failures", { n: tr.state.consecutive_failures })}` : ""}
                        </p>
                        {tr.state?.disabled_reason ? <p className="text-danger">{tr.state.disabled_reason}</p> : null}
                      </div>
                    </div>
                    {canBuild ? (
                      <div className="flex flex-wrap items-center gap-1">
                        <Switch checked={tr.enabled} onCheckedChange={() => toggle.mutate(tr)} aria-label={t("enabledFor", { name: tr.name })} />
                        <Button size="sm" variant="secondary" onClick={() => fire.mutate(tr)} disabled={!tr.enabled || fire.isPending}>
                          <Play />
                          {t("runNow")}
                        </Button>
                        {tr.kind === "email" ? (
                          <Button size="sm" variant="secondary" onClick={() => setEmailing(tr)} disabled={!tr.enabled}>
                            <Send />
                            {t("sendTestEmail")}
                          </Button>
                        ) : null}
                        {tr.kind === "webhook" ? (
                          <Button size="icon-sm" variant="ghost" aria-label={t("rotate")} title={t("rotate")} onClick={() => setRotating(tr)}>
                            <KeyRound />
                          </Button>
                        ) : null}
                        <Button size="icon-sm" variant="ghost" aria-label={t("edit", { name: tr.name })} onClick={() => setEditing(tr)}>
                          <Pencil />
                        </Button>
                        <Button size="icon-sm" variant="ghost" aria-label={t("delete", { name: tr.name })} onClick={() => setDeleting(tr)}>
                          <Trash2 />
                        </Button>
                      </div>
                    ) : null}
                  </div>
                  {tr.kind === "webhook" && tr.webhook_url ? (
                    <details className="mt-3 text-xs">
                      <summary className="cursor-pointer text-fg-muted hover:text-fg">{t("howToCall")}</summary>
                      <p className="my-2 text-fg-muted">{t("signatureRecipe")}</p>
                      <CodeBlock code={curlExample(tr.webhook_url, { secret: t("curlSecret"), body: t("curlBody") })} language="bash" />
                    </details>
                  ) : null}
                  <button
                    type="button"
                    className="mt-3 flex items-center gap-1 text-xs text-fg-muted hover:text-fg"
                    aria-expanded={open}
                    onClick={() => setExpanded(open ? null : tr.id)}
                  >
                    {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
                    {t("history", { n: history.length })}
                  </button>
                  {open ? (
                    history.length === 0 ? (
                      <p className="mt-2 text-xs text-fg-subtle">{t("historyEmpty")}</p>
                    ) : (
                      <ol className="mt-2 divide-y divide-border rounded-md border border-border">
                        {history.map((entry, i) => (
                          <li key={`${entry.at}-${i}`} className="flex flex-wrap items-center gap-2 px-2.5 py-1.5 text-xs">
                            <time className="w-36 tabular text-fg-muted" dateTime={entry.at}>
                              {formatDate(entry.at, locale, true)}
                            </time>
                            {entry.status === "not_deployed" ? (
                              <Badge tone="warning">{t("notDeployed")}</Badge>
                            ) : (
                              <RunStatusBadge status={entry.status} />
                            )}
                            {entry.run_id ? (
                              <Link className="font-mono text-fg-muted hover:text-fg hover:underline" href={`/app/projects/${projectId}/traces/${entry.run_id}`}>
                                {entry.run_id.slice(0, 8)}
                              </Link>
                            ) : null}
                            {entry.error ? <span className="min-w-0 flex-1 truncate text-danger">{entry.error}</span> : null}
                          </li>
                        ))}
                      </ol>
                    )
                  ) : null}
                </Card>
              </li>
            );
          })}
        </ul>
      )}

      <TriggerDialog
        projectId={projectId}
        workflow={workflow}
        palette={palette}
        open={creating || editing !== null}
        trigger={editing}
        onClose={() => {
          setCreating(false);
          setEditing(null);
        }}
        onSaved={(saved, created) => {
          setCreating(false);
          setEditing(null);
          refresh();
          toast.success(created ? t("created") : t("updated"));
          if (created && saved.secret) setSecret(saved);
        }}
      />
      <SecretDialog trigger={secret} onClose={() => setSecret(null)} />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(o) => (!o ? setDeleting(null) : undefined)}
        title={t("deleteTitle", { name: deleting?.name ?? "" })}
        description={t("deleteDescription")}
        confirmLabel={tc("delete")}
        cancelLabel={tc("cancel")}
        destructive
        loading={remove.isPending}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting);
        }}
      />
      <ConfirmDialog
        open={rotating !== null}
        onOpenChange={(o) => (!o ? setRotating(null) : undefined)}
        title={t("rotateTitle")}
        description={t("rotateDescription")}
        confirmLabel={t("rotate")}
        cancelLabel={tc("cancel")}
        destructive
        loading={rotate.isPending}
        onConfirm={() => {
          if (rotating) rotate.mutate(rotating);
        }}
      />
      <Dialog open={emailing !== null} onOpenChange={(o) => (!o ? setEmailing(null) : undefined)}>
        <DialogContent
          title={t("testEmailTitle")}
          description={emailing?.inbound_address ? t("testEmailDescription", { address: emailing.inbound_address }) : undefined}
          footer={
            <>
              <Button variant="ghost" onClick={() => setEmailing(null)}>
                {tc("cancel")}
              </Button>
              <Button variant="primary" loading={simulate.isPending} onClick={() => emailing && simulate.mutate(emailing)}>
                <Send />
                {t("sendTestEmail")}
              </Button>
            </>
          }
        >
          <div className="space-y-3">
            <Field label={t("emailFrom")} htmlFor="test-email-from">
              <Input id="test-email-from" type="email" value={email.from} onChange={(e) => setEmail((s) => ({ ...s, from: e.target.value }))} />
            </Field>
            <Field label={t("emailSubject")} htmlFor="test-email-subject">
              <Input id="test-email-subject" value={email.subject} onChange={(e) => setEmail((s) => ({ ...s, subject: e.target.value }))} />
            </Field>
            <Field label={t("emailText")} htmlFor="test-email-text">
              <Textarea id="test-email-text" rows={4} value={email.text} onChange={(e) => setEmail((s) => ({ ...s, text: e.target.value }))} />
            </Field>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
