"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  ConfirmDialog,
  CopyButton,
  Dialog,
  DialogContent,
  ErrorState,
  Field,
  Input,
  RadioCards,
  SkeletonRows,
  type StatusTone,
  StatusDot,
  toast,
} from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, GitBranch, KeyRound, RefreshCw, Unplug } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";
import { formatDate, formatRelative, localeTag } from "@/lib/format";
import { useRole } from "@/lib/hooks/use-me";
import { errorMessage } from "@/lib/studio/hooks";

export type GithubMode = "app" | "pat";
export type GithubState = "disconnected" | "pending" | "synced" | "error";

export interface GithubStatus {
  connected: boolean;
  state: GithubState;
  mode: GithubMode | null;
  repo: string | null;
  repo_url: string | null;
  branch: string | null;
  app_available: boolean;
  app_install_url: string | null;
  webhook_url: string;
  webhook: "app" | "auto" | "manual" | null;
  connected_at: string | null;
  connected_by: string | null;
  head: string | null;
  last_push_at: string | null;
  last_push_sha: string | null;
  last_pull_at: string | null;
  last_pull_sha: string | null;
  last_sync_at: string | null;
  last_error: string | null;
  last_error_at: string | null;
  last_conflicts: string[] | null;
  webhook_secret?: string;
}

interface ConnectBody {
  repo: string;
  branch: string | null;
  mode: GithubMode;
  token: string | null;
}

const REPO_RE = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})\/[A-Za-z0-9._-]{1,100}$/;
const STATE_TONE: Record<GithubState, StatusTone> = {
  synced: "success",
  pending: "warning",
  error: "danger",
  disconnected: "neutral",
};

export const githubKeys = {
  status: (projectId: string) => ["projects", projectId, "github"] as const,
};

function shortSha(sha: string | null | undefined): string {
  return sha ? sha.slice(0, 7) : "";
}

/** GitHub sync section of the project settings page (status, connect, sync now, disconnect). */
export function GithubSettings({ projectId }: { projectId: string }) {
  const t = useTranslations("github.sync");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const isAdmin = useRole("admin");
  const canSync = useRole("builder");
  const key = githubKeys.status(projectId);
  const status = useQuery({
    queryKey: key,
    queryFn: () => http.get<GithubStatus>(`/projects/${projectId}/github`),
    refetchInterval: (query) => (query.state.data?.state === "pending" ? 4000 : false),
  });
  const [formOpen, setFormOpen] = React.useState(false);
  const [secret, setSecret] = React.useState<string | null>(null);
  const [disconnectOpen, setDisconnectOpen] = React.useState(false);
  const [rotateOpen, setRotateOpen] = React.useState(false);

  const sync = useMutation({
    mutationFn: () => http.post<{ queued: boolean }>(`/projects/${projectId}/github/sync`),
    onSuccess: () => {
      toast.success(t("syncQueued"));
      window.setTimeout(() => void qc.invalidateQueries({ queryKey: key }), 4000);
    },
    onError: (err) => toast.error(errorMessage(err, tc("errorGeneric"))),
  });
  const disconnect = useMutation({
    mutationFn: () => http.del(`/projects/${projectId}/github`),
    onSuccess: () => {
      setDisconnectOpen(false);
      toast.success(t("disconnected"));
      void qc.invalidateQueries({ queryKey: key });
      void qc.invalidateQueries({ queryKey: ["projects", projectId], exact: true });
    },
    onError: (err) => toast.error(errorMessage(err, tc("errorGeneric"))),
  });
  const rotate = useMutation({
    mutationFn: () => http.post<{ webhook_secret: string }>(`/projects/${projectId}/github/webhook-secret`),
    onSuccess: (res) => {
      setRotateOpen(false);
      setSecret(res.webhook_secret);
      void qc.invalidateQueries({ queryKey: key });
    },
    onError: (err) => toast.error(errorMessage(err, tc("errorGeneric"))),
  });

  const onConnected = (res: GithubStatus, firstTime: boolean) => {
    const { webhook_secret: revealed, ...rest } = res;
    qc.setQueryData(key, rest);
    void qc.invalidateQueries({ queryKey: ["projects", projectId], exact: true });
    setFormOpen(false);
    toast.success(firstTime ? t("connected") : t("saved"));
    if (revealed) setSecret(revealed);
  };

  if (status.isLoading) {
    return (
      <Card>
        <CardHeader title={t("title")} description={t("description")} />
        <CardBody>
          <SkeletonRows rows={4} />
        </CardBody>
      </Card>
    );
  }
  if (status.error || !status.data) {
    return (
      <Card>
        <CardHeader title={t("title")} description={t("description")} />
        <CardBody>
          <ErrorState
            title={tc("errorTitle")}
            description={errorMessage(status.error, tc("errorGeneric"))}
            onRetry={() => void status.refetch()}
            retryLabel={tc("retry")}
          />
        </CardBody>
      </Card>
    );
  }

  const s = status.data;
  return (
    <Card>
      <CardHeader
        title={t("title")}
        description={t("description")}
        actions={
          <Badge tone={STATE_TONE[s.state]}>
            <StatusDot tone={STATE_TONE[s.state]} pulse={s.state === "pending"} />
            {t(`state.${s.state}`)}
          </Badge>
        }
      />
      {!s.connected ? (
        <CardBody className="flex flex-col gap-4">
          {isAdmin ? (
            <ConnectForm projectId={projectId} status={s} onDone={(res) => onConnected(res, true)} />
          ) : (
            <>
              <p className="text-sm text-fg-muted">{t("notConnected")}</p>
              <Alert tone="info">{t("readOnly")}</Alert>
            </>
          )}
        </CardBody>
      ) : (
        <>
          <CardBody className="flex flex-col gap-4">
            <ConnectedDetails status={s} />
            {s.last_error ? (
              <Alert tone="danger" title={t("lastError")}>
                <p>{s.last_error}</p>
                {s.last_error_at ? <ErrorTime value={s.last_error_at} /> : null}
              </Alert>
            ) : null}
            {s.last_conflicts && s.last_conflicts.length > 0 ? (
              <Alert tone="warning" title={t("conflicts")}>
                <ul className="mt-1 list-inside list-disc font-mono text-xs">
                  {s.last_conflicts.map((path) => (
                    <li key={path}>{path}</li>
                  ))}
                </ul>
                <p className="mt-1 text-xs">{t("conflictsHint")}</p>
              </Alert>
            ) : null}
            <WebhookInfo status={s} canRotate={isAdmin} onRotate={() => setRotateOpen(true)} />
            {!isAdmin ? <Alert tone="info">{t("readOnly")}</Alert> : null}
          </CardBody>
          <CardFooter className="flex-wrap gap-2">
            {s.repo_url ? (
              <Button asChild variant="ghost" className="mr-auto">
                <a href={s.repo_url} target="_blank" rel="noreferrer">
                  {t("openRepo")}
                  <ArrowUpRight />
                </a>
              </Button>
            ) : null}
            {isAdmin ? (
              <>
                <Button variant="danger" onClick={() => setDisconnectOpen(true)}>
                  <Unplug />
                  {t("disconnect")}
                </Button>
                <Button variant="secondary" onClick={() => setFormOpen(true)}>
                  <GitBranch />
                  {t("reconfigure")}
                </Button>
              </>
            ) : null}
            {canSync ? (
              <Button variant="primary" loading={sync.isPending} onClick={() => sync.mutate()}>
                <RefreshCw />
                {t("syncNow")}
              </Button>
            ) : null}
          </CardFooter>
        </>
      )}

      <Dialog open={formOpen} onOpenChange={setFormOpen}>
        <DialogContent title={t("reconfigureTitle")} description={t("description")}>
          {formOpen ? <ConnectForm projectId={projectId} status={s} onDone={(res) => onConnected(res, false)} /> : null}
        </DialogContent>
      </Dialog>

      <Dialog
        open={secret !== null}
        onOpenChange={(open) => {
          if (!open) setSecret(null);
        }}
      >
        <DialogContent
          title={t("secretTitle")}
          description={t("secretDescription")}
          footer={
            <Button variant="primary" onClick={() => setSecret(null)}>
              {t("done")}
            </Button>
          }
        >
          <div className="flex flex-col gap-4">
            <Field label={t("webhookUrl")}>
              <CopyField value={s.webhook_url} copyLabel={tc("copy")} />
            </Field>
            <Field label={t("secret")}>
              <CopyField value={secret ?? ""} copyLabel={tc("copy")} />
            </Field>
            <p className="text-sm text-fg-muted">{t("secretSteps")}</p>
          </div>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={disconnectOpen}
        onOpenChange={setDisconnectOpen}
        title={t("disconnectTitle", { repo: s.repo ?? "" })}
        description={t("disconnectDescription")}
        confirmLabel={t("disconnect")}
        cancelLabel={tc("cancel")}
        destructive
        loading={disconnect.isPending}
        onConfirm={() => disconnect.mutate()}
      />
      <ConfirmDialog
        open={rotateOpen}
        onOpenChange={setRotateOpen}
        title={t("rotateTitle")}
        description={t("rotateDescription")}
        confirmLabel={t("rotateSecret")}
        cancelLabel={tc("cancel")}
        destructive
        loading={rotate.isPending}
        onConfirm={() => rotate.mutate()}
      />
    </Card>
  );
}

function CopyField({ value, copyLabel }: { value: string; copyLabel: string }) {
  return (
    <div className="flex items-center gap-1 rounded-md border border-border bg-subtle px-2.5 py-1.5">
      <code className="min-w-0 flex-1 break-all font-mono text-xs">{value}</code>
      <CopyButton value={value} label={copyLabel} />
    </div>
  );
}

function ErrorTime({ value }: { value: string }) {
  const locale = localeTag(useLocale());
  return (
    <p className="mt-1 text-xs" title={formatDate(value, locale, true)}>
      {formatRelative(value, locale)}
    </p>
  );
}

function When({ at, sha }: { at: string | null; sha?: string | null }) {
  const t = useTranslations("github.sync");
  const locale = localeTag(useLocale());
  if (!at) return <span className="text-fg-subtle">{t("never")}</span>;
  return (
    <span className="tabular-nums" title={formatDate(at, locale, true)}>
      {formatRelative(at, locale)}
      {sha ? <code className="ml-1.5 font-mono text-xs text-fg-muted">{shortSha(sha)}</code> : null}
    </span>
  );
}

function ConnectedDetails({ status: s }: { status: GithubStatus }) {
  const t = useTranslations("github.sync");
  return (
    <dl className="grid gap-3 text-sm sm:grid-cols-2">
      <div>
        <dt className="text-xs text-fg-subtle">{t("repository")}</dt>
        <dd className="flex min-w-0 items-center gap-1.5">
          <span className="truncate font-medium">{s.repo}</span>
          <Badge tone="outline">
            <GitBranch className="size-3" />
            {s.branch}
          </Badge>
          {s.mode ? <Badge tone="neutral">{t(`modeLabel.${s.mode}`)}</Badge> : null}
        </dd>
      </div>
      <div>
        <dt className="text-xs text-fg-subtle">{t("head")}</dt>
        <dd>{s.head ? <code className="font-mono text-xs">{shortSha(s.head)}</code> : <span className="text-fg-subtle">—</span>}</dd>
      </div>
      <div>
        <dt className="text-xs text-fg-subtle">{t("lastPush")}</dt>
        <dd>
          <When at={s.last_push_at} sha={s.last_push_sha} />
        </dd>
      </div>
      <div>
        <dt className="text-xs text-fg-subtle">{t("lastPull")}</dt>
        <dd>
          <When at={s.last_pull_at} sha={s.last_pull_sha} />
        </dd>
      </div>
      <div>
        <dt className="text-xs text-fg-subtle">{t("lastSync")}</dt>
        <dd>
          <When at={s.last_sync_at} />
        </dd>
      </div>
    </dl>
  );
}

function WebhookInfo({ status: s, canRotate, onRotate }: { status: GithubStatus; canRotate: boolean; onRotate: () => void }) {
  const t = useTranslations("github.sync");
  const tc = useTranslations("common");
  const label = s.webhook === "app" ? t("webhookApp") : s.webhook === "auto" ? t("webhookAuto") : t("webhookManual");
  return (
    <div className="flex flex-col gap-2 rounded-md border border-border p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-medium">{t("webhook")}</p>
        <Badge tone={s.webhook === "manual" ? "warning" : "success"}>{label}</Badge>
      </div>
      {s.webhook === "manual" ? (
        <>
          <p className="text-xs text-fg-muted">{t("webhookManualHint")}</p>
          <CopyField value={s.webhook_url} copyLabel={tc("copy")} />
        </>
      ) : null}
      {s.mode === "pat" && canRotate ? (
        <div>
          <Button variant="ghost" size="sm" onClick={onRotate}>
            <KeyRound />
            {t("rotateSecret")}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function ConnectForm({
  projectId,
  status,
  onDone,
}: {
  projectId: string;
  status: GithubStatus;
  onDone: (res: GithubStatus) => void;
}) {
  const t = useTranslations("github.sync");
  const tc = useTranslations("common");
  const [mode, setMode] = React.useState<GithubMode>(status.mode ?? (status.app_available ? "app" : "pat"));
  const [repo, setRepo] = React.useState(status.repo ?? "");
  const [branch, setBranch] = React.useState(status.branch ?? "");
  const [token, setToken] = React.useState("");
  const [tried, setTried] = React.useState(false);

  const keepToken = status.connected && status.mode === "pat" && mode === "pat" && repo.trim().toLowerCase() === (status.repo ?? "").toLowerCase();
  const repoError = !REPO_RE.test(repo.trim()) ? t("repoInvalid") : null;
  const tokenError = mode === "pat" && !keepToken && !token.trim() ? t("tokenRequired") : null;

  const connect = useMutation({
    mutationFn: (body: ConnectBody) => http.put<GithubStatus>(`/projects/${projectId}/github`, { ...body }),
    onSuccess: (res) => {
      setToken("");
      onDone(res);
    },
    onError: (err) => toast.error(errorMessage(err, tc("errorGeneric"))),
  });

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        setTried(true);
        if (repoError || tokenError) return;
        connect.mutate({
          repo: repo.trim(),
          branch: branch.trim() || null,
          mode,
          token: mode === "pat" && token.trim() ? token.trim() : null,
        });
      }}
    >
      <fieldset>
        <legend className="mb-1.5 text-sm font-medium">{t("mode")}</legend>
        <RadioCards
          value={mode}
          onValueChange={(v) => setMode(v as GithubMode)}
          className="grid-cols-1 sm:grid-cols-2"
          options={[
            {
              value: "app",
              label: t("modeApp"),
              description: status.app_available ? t("modeAppDescription") : t("modeAppUnavailable"),
              disabled: !status.app_available,
            },
            { value: "pat", label: t("modePat"), description: t("modePatDescription") },
          ]}
        />
        {mode === "app" && status.app_install_url ? (
          <Button asChild variant="link" size="sm" className="mt-2">
            <a href={status.app_install_url} target="_blank" rel="noreferrer">
              {t("installApp")}
              <ArrowUpRight />
            </a>
          </Button>
        ) : null}
      </fieldset>
      <div className="grid gap-4 sm:grid-cols-[2fr_1fr]">
        <Field label={t("repo")} htmlFor="gh-repo" hint={t("repoHint")} error={tried ? repoError : null}>
          <Input
            id="gh-repo"
            value={repo}
            maxLength={200}
            autoComplete="off"
            spellCheck={false}
            placeholder="acme/soporte"
            aria-invalid={tried && Boolean(repoError)}
            onChange={(e) => setRepo(e.target.value)}
          />
        </Field>
        <Field label={t("branch")} htmlFor="gh-branch" hint={t("branchHint")}>
          <Input
            id="gh-branch"
            value={branch}
            maxLength={200}
            autoComplete="off"
            spellCheck={false}
            placeholder="main"
            onChange={(e) => setBranch(e.target.value)}
          />
        </Field>
      </div>
      {mode === "pat" ? (
        <Field
          label={t("token")}
          htmlFor="gh-token"
          hint={keepToken ? `${t("tokenHint")} ${t("tokenKeep")}` : t("tokenHint")}
          error={tried ? tokenError : null}
        >
          <Input
            id="gh-token"
            type="password"
            value={token}
            maxLength={500}
            autoComplete="off"
            spellCheck={false}
            placeholder="github_pat_…"
            aria-invalid={tried && Boolean(tokenError)}
            onChange={(e) => setToken(e.target.value)}
          />
        </Field>
      ) : null}
      <div className="flex justify-end">
        <Button type="submit" variant="primary" loading={connect.isPending}>
          {status.connected ? tc("save") : t("connect")}
        </Button>
      </div>
    </form>
  );
}
