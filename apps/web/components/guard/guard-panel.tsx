"use client";

import {
  Alert,
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  SkeletonRows,
  StatusDot,
  Switch,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  toast,
} from "@messer/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, Braces, FileText, History, RefreshCw, Save, ShieldCheck, Sparkles, Undo2 } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { billingHref, useUpgradeDialog } from "@/components/billing";
import { ApiError, http } from "@/lib/api";
import { formatRelative, localeTag } from "@/lib/format";
import { useRole } from "@/lib/hooks/use-me";

import { DecisionsTable } from "./decisions-table";
import { guardKeys, guardPath, useGuard } from "./hooks";
import { IssueList } from "./issues";
import { MetricsCards } from "./metrics-cards";
import { type EditorMode, PlaybookEditor } from "./playbook-editor";
import { clientIssues, emptyPlaybook, fingerprint, normalizePlaybook, serialize } from "./playbook-draft";
import type { GuardDetail, Issue, Playbook } from "./types";

type PanelTab = "playbook" | "decisions";

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message || fallback;
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}

function issuesFromError(err: unknown): Issue[] | null {
  if (!(err instanceof ApiError) || err.code !== "invalid_playbook") return null;
  const raw = (err.details as { issues?: unknown }).issues;
  return Array.isArray(raw) ? (raw as Issue[]) : null;
}

/**
 * The "Guard" tab of the Agent builder: enable toggle, playbook editor (form and JSON), regeneration, metrics
 * and recent decisions. Mount with the project id and the agent's workforce name.
 */
export function GuardPanel({
  projectId,
  member,
  canBuild: canBuildProp,
}: {
  projectId: string;
  member: string;
  /** Defaults to the current user's role (builder or above). */
  canBuild?: boolean;
}) {
  const t = useTranslations("guard");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const roleCanBuild = useRole("builder");
  const canBuild = canBuildProp ?? roleCanBuild;
  const guard = useGuard(projectId, member);
  const upgrade = useUpgradeDialog();

  const [tab, setTab] = React.useState<PanelTab>("playbook");
  const [mode, setMode] = React.useState<EditorMode>("form");
  const [draft, setDraft] = React.useState<Playbook | null>(null);
  const [serverPrint, setServerPrint] = React.useState<string>("");
  const [saveIssues, setSaveIssues] = React.useState<Issue[] | null>(null);
  const [jsonError, setJsonError] = React.useState<string | null>(null);
  const [confirmRegenerate, setConfirmRegenerate] = React.useState(false);
  const [confirmDisable, setConfirmDisable] = React.useState(false);
  const [openPolicies, setOpenPolicies] = React.useState<Set<string>>(new Set());

  const detail = guard.data;
  const serverPlaybook = React.useMemo(() => (detail?.playbook ? normalizePlaybook(detail) : null), [detail]);

  // Adopt server state; keep an unsaved draft unless it still equals the previous server version.
  const [adopted, setAdopted] = React.useState<GuardDetail | undefined>(undefined);
  if (detail !== adopted) {
    setAdopted(detail);
    const nextPrint = fingerprint(serverPlaybook);
    if (draft === null || fingerprint(draft) === serverPrint) setDraft(serverPlaybook);
    setServerPrint(nextPrint);
  }

  const dirty = draft !== null && fingerprint(draft) !== serverPrint;
  const local = React.useMemo(() => (draft ? clientIssues(draft) : []), [draft]);
  const issues: Issue[] = React.useMemo(() => {
    const remote = dirty ? (saveIssues ?? []) : (saveIssues ?? detail?.issues ?? []);
    return [...local, ...remote];
  }, [dirty, saveIssues, detail, local]);
  const hasErrors = jsonError !== null || issues.some((i) => i.level === "error");

  const adopt = (next: GuardDetail, force: boolean) => {
    qc.setQueryData(guardKeys.detail(projectId, member), next);
    if (force) {
      const pb = next.playbook ? normalizePlaybook(next) : null;
      setDraft(pb);
      setServerPrint(fingerprint(pb));
      setAdopted(next);
    }
    void qc.invalidateQueries({ queryKey: ["projects", projectId, "workforce"] });
  };

  const save = useMutation({
    mutationFn: (playbook: Playbook) =>
      http.put<GuardDetail>(guardPath(projectId, member), {
        playbook: serialize(playbook) as unknown as Record<string, unknown>,
      }),
    onSuccess: (next) => {
      setSaveIssues(null);
      adopt(next, true);
      toast.success(t("editor.saved"));
    },
    onError: (err) => {
      const found = issuesFromError(err);
      if (found) {
        setSaveIssues(found);
        toast.error(t("editor.invalid"));
      } else if (!upgrade.handle(err)) {
        toast.error(errorMessage(err, tc("errorGeneric")));
      }
    },
  });

  const regenerate = useMutation({
    mutationFn: () => http.post<GuardDetail>(guardPath(projectId, member, "/regenerate")),
    onSuccess: (next) => {
      setSaveIssues(null);
      setConfirmRegenerate(false);
      adopt(next, true);
      setOpenPolicies(new Set());
      toast.success(t("generate.done"));
    },
    onError: (err) => {
      setConfirmRegenerate(false);
      if (!upgrade.handle(err)) toast.error(errorMessage(err, tc("errorGeneric")));
    },
  });

  const toggle = useMutation({
    mutationFn: (enable: boolean) =>
      http.post<GuardDetail>(guardPath(projectId, member, enable ? "/enable" : "/disable")),
    onSuccess: (next) => {
      setConfirmDisable(false);
      adopt(next, false);
      toast.success(next.enabled ? t("toggle.enabled", { member }) : t("toggle.disabled", { member }));
    },
    onError: (err) => {
      setConfirmDisable(false);
      const found = issuesFromError(err);
      if (found) setSaveIssues(found);
      if (!upgrade.handle(err)) toast.error(errorMessage(err, tc("errorGeneric")));
    },
  });

  if (guard.isLoading) {
    return (
      <div className="px-4 py-4 md:px-5">
        <SkeletonRows rows={6} />
      </div>
    );
  }
  if (guard.error || !detail) {
    return (
      <div className="px-4 py-4 md:px-5">
        <ErrorState
          title={tc("errorTitle")}
          description={errorMessage(guard.error, tc("errorGeneric"))}
          onRetry={() => void guard.refetch()}
          retryLabel={tc("retry")}
        />
      </div>
    );
  }

  const hasPlaybook = detail.playbook !== null;
  const readOnly = !canBuild;
  const toggleBlockedReason = !canBuild
    ? t("toggle.viewer")
    : !detail.enabled && !hasPlaybook
      ? t("toggle.needsPlaybook")
      : !detail.enabled && dirty
        ? t("toggle.unsaved")
        : !detail.enabled && hasErrors
          ? t("toggle.hasErrors")
          : null;
  const source =
    detail.generated_by === "llm"
      ? t("generate.byLlm", { model: String(detail.meta.model ?? "LLM") })
      : detail.generated_by === "rules"
        ? t("generate.byRules")
        : detail.generated_by === "manual"
          ? t("generate.byManual")
          : null;
  const notes = Array.isArray(detail.meta.warnings) ? detail.meta.warnings.map(String) : [];

  const onToggle = (on: boolean) => {
    if (on) toggle.mutate(true);
    else setConfirmDisable(true);
  };
  const onRegenerate = () => {
    if (hasPlaybook || dirty) setConfirmRegenerate(true);
    else regenerate.mutate();
  };

  return (
    <div className="flex flex-col gap-4 px-4 py-4 md:px-5">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="flex flex-wrap items-center gap-2 text-base font-semibold">
            <ShieldCheck className="size-4 text-fg-muted" aria-hidden />
            {t("title")}
            <Badge tone={detail.enabled ? "success" : "neutral"}>
              <StatusDot tone={detail.enabled ? "success" : "neutral"} />
              {detail.enabled ? t("toggle.on") : t("toggle.off")}
            </Badge>
            {dirty ? (
              <Badge tone="warning">
                <StatusDot tone="warning" />
                {t("editor.unsaved")}
              </Badge>
            ) : null}
          </h2>
          <p className="mt-1 max-w-2xl text-xs text-fg-muted">{t("subtitle")}</p>
          {source ? (
            <p className="mt-1 text-xs text-fg-subtle">
              {source}
              {detail.updated_at ? ` · ${t("generate.updated", { when: formatRelative(detail.updated_at, locale) })}` : ""}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm" title={toggleBlockedReason ?? undefined}>
            <Switch
              checked={detail.enabled}
              onCheckedChange={onToggle}
              disabled={toggle.isPending || (toggleBlockedReason !== null && !detail.enabled) || !canBuild}
              aria-label={t("toggle.label")}
            />
            {t("toggle.label")}
          </label>
          {canBuild && hasPlaybook ? (
            <Button size="sm" onClick={onRegenerate} loading={regenerate.isPending}>
              <RefreshCw />
              {regenerate.isPending ? t("generate.running") : t("generate.regenerate")}
            </Button>
          ) : null}
        </div>
      </div>

      {toggleBlockedReason && !detail.enabled && canBuild ? (
        <p className="-mt-2 text-xs text-fg-subtle">{toggleBlockedReason}</p>
      ) : null}
      {!detail.plan_allows ? (
        <Alert
          tone="warning"
          title={t("toggle.planTitle")}
          action={
            <Button asChild size="sm" variant="dark">
              <Link href={billingHref(null)}>
                {t("toggle.seePlans")}
                <ArrowUpRight />
              </Link>
            </Button>
          }
        >
          {t("toggle.planDescription")}
        </Alert>
      ) : null}

      <MetricsCards projectId={projectId} member={member} />

      <Tabs value={tab} onValueChange={(v) => setTab(v as PanelTab)} className="flex flex-col">
        <TabsList>
          <TabsTrigger value="playbook">
            <FileText aria-hidden />
            {t("tabs.playbook")}
          </TabsTrigger>
          <TabsTrigger value="decisions">
            <History aria-hidden />
            {t("tabs.decisions")}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="playbook" className="pt-4">
          {!draft ? (
            <EmptyState
              icon={<ShieldCheck />}
              title={t("empty.title")}
              description={canBuild ? t("empty.description") : t("empty.viewerDescription")}
              action={
                canBuild ? (
                  <div className="flex flex-wrap justify-center gap-2">
                    <Button variant="primary" loading={regenerate.isPending} onClick={() => regenerate.mutate()}>
                      <Sparkles />
                      {regenerate.isPending ? t("generate.running") : t("generate.button")}
                    </Button>
                    <Button onClick={() => setDraft(emptyPlaybook(detail))}>{t("empty.blank")}</Button>
                  </div>
                ) : null
              }
            />
          ) : (
            <div className="flex flex-col gap-4">
              <div className="flex flex-wrap items-center gap-2">
                <div className="inline-flex rounded-md border border-border p-0.5" role="group" aria-label={t("tabs.playbook")}>
                  {(["form", "json"] as const).map((m) => (
                    <Button
                      key={m}
                      size="sm"
                      variant={mode === m ? "dark" : "ghost"}
                      aria-pressed={mode === m}
                      onClick={() => {
                        if (m === mode || (mode === "json" && jsonError)) return;
                        setMode(m);
                      }}
                      disabled={mode === "json" && jsonError !== null && m === "form"}
                    >
                      {m === "json" ? <Braces /> : <FileText />}
                      {t(`editor.${m}`)}
                    </Button>
                  ))}
                </div>
                {issues.length ? (
                  <span className="text-xs text-fg-muted">
                    {issues.some((i) => i.level === "error")
                      ? t("editor.issues.errors", { count: issues.filter((i) => i.level === "error").length })
                      : null}
                    {issues.some((i) => i.level === "error") && issues.some((i) => i.level === "warning") ? " · " : null}
                    {issues.some((i) => i.level === "warning")
                      ? t("editor.issues.warnings", { count: issues.filter((i) => i.level === "warning").length })
                      : null}
                  </span>
                ) : null}
                <div className="ml-auto flex items-center gap-2">
                  {readOnly ? <Badge tone="outline">{t("editor.readOnly")}</Badge> : null}
                  {canBuild && dirty ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={save.isPending}
                      onClick={() => {
                        setDraft(serverPlaybook);
                        setSaveIssues(null);
                        setJsonError(null);
                        setMode("form");
                      }}
                    >
                      <Undo2 />
                      {t("editor.discard")}
                    </Button>
                  ) : null}
                  {canBuild ? (
                    <Button
                      variant="primary"
                      size="sm"
                      loading={save.isPending}
                      disabled={!dirty || jsonError !== null || local.some((i) => i.level === "error")}
                      onClick={() => draft && save.mutate(draft)}
                    >
                      <Save />
                      {t("editor.save")}
                    </Button>
                  ) : null}
                </div>
              </div>

              {notes.length && !dirty ? (
                <Alert tone="info" title={t("generate.notes")}>
                  <ul className="list-disc pl-4">
                    {notes.map((n, i) => (
                      <li key={i}>{n}</li>
                    ))}
                  </ul>
                </Alert>
              ) : null}
              {saveIssues && saveIssues.some((i) => i.level === "error") ? (
                <Alert tone="danger" title={t("editor.invalid")}>
                  <IssueList issues={saveIssues.filter((i) => i.level === "error")} className="mt-1" />
                </Alert>
              ) : null}

              <PlaybookEditor
                key={mode}
                detail={detail}
                draft={draft}
                issues={issues}
                mode={mode}
                readOnly={readOnly}
                openPolicies={openPolicies}
                onParseError={setJsonError}
                onChange={(next) => {
                  setDraft(next);
                  setSaveIssues(null);
                }}
              />
            </div>
          )}
        </TabsContent>

        <TabsContent value="decisions" className="pt-4">
          <DecisionsTable projectId={projectId} member={member} />
        </TabsContent>
      </Tabs>

      <ConfirmDialog
        open={confirmRegenerate}
        onOpenChange={setConfirmRegenerate}
        title={t("generate.confirmTitle")}
        description={t("generate.confirmDescription")}
        confirmLabel={t("generate.confirm")}
        cancelLabel={tc("cancel")}
        loading={regenerate.isPending}
        onConfirm={() => regenerate.mutate()}
      />
      <ConfirmDialog
        open={confirmDisable}
        onOpenChange={setConfirmDisable}
        title={t("toggle.disableTitle")}
        description={t("toggle.disableDescription", { member })}
        confirmLabel={t("toggle.disableConfirm")}
        cancelLabel={tc("cancel")}
        loading={toggle.isPending}
        onConfirm={() => toggle.mutate(false)}
      />
      {upgrade.dialog}
    </div>
  );
}
