"use client";

import {
  Alert,
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Kbd,
  SkeletonRows,
  StatusDot,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  toast,
} from "@messer/ui";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Bot, Code2, FlaskConical, History, Save, Settings2, ShieldCheck, Undo2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { GuardPanel } from "@/components/guard/guard-panel";
import { ApiError, http } from "@/lib/api";
import { useRole } from "@/lib/hooks/use-me";
import { configFingerprint, normalizeConfig, normalizeContextFiles, validateConfig } from "@/lib/studio/agent-config";
import { errorMessage, isNotFound, studioKeys, useMember, useUnsavedChangesGuard } from "@/lib/studio/hooks";
import type { AgentConfig, MemberDetail } from "@/lib/studio/types";

import { Playground } from "../playground/playground";
import { type CodeError, CodeTab } from "./code-tab";
import { ConfigTab } from "./config-tab";
import { EvalsTab } from "./evals-tab";
import { VersionsTab } from "./versions-tab";

type TabKey = "config" | "code" | "versions" | "evals" | "guard";

function DirtyDot({ label }: { label: string }) {
  return (
    <span className="inline-flex" title={label}>
      <StatusDot tone="warning" />
      <span className="sr-only">{label}</span>
    </span>
  );
}

export function AgentBuilder({ projectId, name }: { projectId: string; name: string }) {
  const t = useTranslations("studio.builder");
  const tc = useTranslations("common");
  const router = useRouter();
  const qc = useQueryClient();
  const canBuild = useRole("builder");
  const member = useMember(projectId, name);
  const base = `/projects/${projectId}/workforce/${encodeURIComponent(name)}`;

  const [tab, setTab] = React.useState<TabKey>("config");
  const [draft, setDraft] = React.useState<AgentConfig | null>(null);
  const [saved, setSaved] = React.useState<AgentConfig | null>(null);
  const [code, setCode] = React.useState<string | null>(null);
  const [codeSaved, setCodeSaved] = React.useState<string | null>(null);
  const [codeError, setCodeError] = React.useState<CodeError | null>(null);
  const [saving, setSaving] = React.useState(false);
  const savedRef = React.useRef<AgentConfig | null>(null);
  const codeSavedRef = React.useRef<string | null>(null);
  const initialTabSet = React.useRef(false);

  /** Take the server state; keep unsaved drafts unless `force`. */
  const adopt = React.useCallback((detail: MemberDetail, force: { config: boolean; code: boolean }) => {
    const server = normalizeConfig(detail);
    const prevSaved = savedRef.current;
    savedRef.current = server;
    setSaved(server);
    setDraft((prev) =>
      force.config || !prev || !prevSaved || configFingerprint(prev) === configFingerprint(prevSaved)
        ? server
        : { ...prev, context_files: server.context_files },
    );
    const prevCode = codeSavedRef.current;
    codeSavedRef.current = detail.code;
    setCodeSaved(detail.code);
    setCode((prev) => (force.code || prev === null || prev === prevCode ? detail.code : prev));
  }, []);

  React.useEffect(() => {
    if (!member.data) return;
    adopt(member.data, { config: false, code: false });
    if (!initialTabSet.current) {
      initialTabSet.current = true;
      if (member.data.source_mode === "code") setTab("code");
    }
  }, [member.data, adopt]);

  const configDirty = Boolean(draft && saved && configFingerprint(draft) !== configFingerprint(saved));
  const codeDirty = code !== null && codeSaved !== null && code !== codeSaved;
  const dirty = configDirty || codeDirty;
  const errors = React.useMemo(() => (draft ? validateConfig(draft) : {}), [draft]);
  const hasErrors = Object.keys(errors).length > 0;
  const guard = useUnsavedChangesGuard(dirty);

  const detail = member.data;
  const codeMode = detail?.source_mode === "code";
  const configReadOnlyReason = !canBuild ? "viewer" : codeMode ? "code_mode" : codeDirty ? "code_dirty" : null;
  const codeReadOnlyReason = !canBuild ? "viewer" : configDirty ? "config_dirty" : null;

  const afterSave = (next: MemberDetail) => {
    qc.setQueryData(studioKeys.member(projectId, name), next);
    void qc.invalidateQueries({ queryKey: studioKeys.members(projectId) });
    void qc.invalidateQueries({ queryKey: studioKeys.members(projectId, "agent") });
  };

  const saveConfig = async () => {
    if (!draft || !detail || saving) return;
    if (hasErrors) {
      setTab("config");
      toast.error(t("fixErrors"));
      return;
    }
    setSaving(true);
    try {
      const body = { ...draft, name: detail.name, context_files: normalizeContextFiles(detail.config.context_files) };
      const next = await http.put<MemberDetail>(`${base}/config`, body as unknown as Record<string, unknown>);
      adopt(next, { config: true, code: false });
      afterSave(next);
      toast.success(t("configSaved"));
    } catch (err) {
      toast.error(errorMessage(err, tc("errorGeneric")));
    } finally {
      setSaving(false);
    }
  };

  const saveCode = async () => {
    if (code === null || saving) return;
    setSaving(true);
    setCodeError(null);
    try {
      const next = await http.put<MemberDetail>(`${base}/code`, { code });
      adopt(next, { config: true, code: true });
      afterSave(next);
      toast.success(next.source_mode === "code" ? t("codeSavedCodeMode") : t("codeSaved"));
    } catch (err) {
      if (err instanceof ApiError && err.code === "syntax_error") {
        const line = typeof err.details.line === "number" ? err.details.line : null;
        const column = typeof err.details.offset === "number" ? err.details.offset : null;
        setCodeError({ message: err.message, line, column });
        setTab("code");
      } else {
        toast.error(errorMessage(err, tc("errorGeneric")));
      }
    } finally {
      setSaving(false);
    }
  };

  const save = () => {
    if (codeDirty) void saveCode();
    else if (configDirty) void saveConfig();
  };

  const discard = () => {
    if (saved) setDraft(saved);
    if (codeSaved !== null) setCode(codeSaved);
    setCodeError(null);
  };

  const saveRef = React.useRef(save);
  React.useEffect(() => {
    saveRef.current = save;
  });
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        saveRef.current();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (member.isLoading || (member.data && (!draft || code === null))) {
    return (
      <div className="grid gap-6 p-6 lg:grid-cols-2">
        <SkeletonRows rows={8} />
        <SkeletonRows rows={8} />
      </div>
    );
  }
  if (member.error || !detail || !draft || code === null) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-10">
        {isNotFound(member.error) ? (
          <EmptyState
            icon={<Bot />}
            title={t("notFound.title")}
            description={t("notFound.description", { name })}
            action={
              <Button asChild variant="secondary">
                <Link href={`/app/projects/${projectId}/agents`}>{t("notFound.back")}</Link>
              </Button>
            }
          />
        ) : (
          <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void member.refetch()} retryLabel={tc("retry")} />
        )}
      </div>
    );
  }
  if (detail.kind !== "agent") {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-10">
        <Alert tone="info">{t("notAnAgent", { name })}</Alert>
      </div>
    );
  }

  const tabLabel = (key: TabKey, Icon: typeof Settings2, label: string, isDirty = false) => (
    <TabsTrigger value={key}>
      <Icon aria-hidden />
      {label}
      {isDirty ? <DirtyDot label={t("unsaved")} /> : null}
    </TabsTrigger>
  );

  return (
    <div className="flex flex-col lg:h-[calc(100dvh-8rem-1px)] lg:flex-row">
      <section className="flex min-h-0 flex-col border-border lg:w-[56%] lg:border-r" aria-label={t("editorLabel")}>
        <div className="flex flex-wrap items-start gap-3 border-b border-border px-4 py-3 md:px-5">
          <Button asChild variant="ghost" size="icon-sm" aria-label={t("back")}>
            <Link href={`/app/projects/${projectId}/agents`}>
              <ArrowLeft />
            </Link>
          </Button>
          <div className="min-w-0 flex-1">
            <h1 className="flex flex-wrap items-center gap-2 text-base font-semibold">
              <span className="font-mono">{detail.name}</span>
              <Badge tone="outline">v{detail.current_version}</Badge>
              {codeMode ? <Badge tone="info">{t("codeModeBadge")}</Badge> : null}
              {dirty ? (
                <Badge tone="warning">
                  <StatusDot tone="warning" />
                  {t("unsaved")}
                </Badge>
              ) : null}
            </h1>
            <p className="mt-0.5 truncate text-xs text-fg-muted">{detail.description || t("noDescription")}</p>
          </div>
          {canBuild ? (
            <div className="flex items-center gap-2">
              {dirty ? (
                <Button variant="ghost" size="sm" onClick={discard} disabled={saving}>
                  <Undo2 />
                  {t("discard")}
                </Button>
              ) : null}
              <Button
                variant="primary"
                size="sm"
                onClick={save}
                loading={saving}
                disabled={!dirty || (configDirty && hasErrors)}
                title={t("saveShortcut")}
              >
                <Save />
                {codeDirty ? t("saveCode") : t("save")}
                <Kbd className="hidden border-accent-fg/30 bg-transparent text-accent-fg xl:inline-flex">⌘S</Kbd>
              </Button>
            </div>
          ) : null}
        </div>

        <Tabs value={tab} onValueChange={(v) => setTab(v as TabKey)} className="flex min-h-0 flex-1 flex-col">
          <TabsList className="px-3 md:px-4">
            {tabLabel("config", Settings2, t("tabs.config"), configDirty)}
            {tabLabel("code", Code2, t("tabs.code"), codeDirty)}
            {tabLabel("versions", History, t("tabs.versions"))}
            {tabLabel("evals", FlaskConical, t("tabs.evals"))}
            {tabLabel("guard", ShieldCheck, t("tabs.guard"))}
          </TabsList>
          <TabsContent value="config" className="min-h-0 flex-1 overflow-y-auto pt-0">
            <ConfigTab
              projectId={projectId}
              member={detail.name}
              config={draft}
              serverContextFiles={normalizeContextFiles(detail.config.context_files)}
              onChange={(patch) => setDraft((prev) => (prev ? { ...prev, ...patch } : prev))}
              readOnly={configReadOnlyReason !== null}
              readOnlyReason={configReadOnlyReason}
              codeMode={codeMode}
              errors={errors}
              onOpenCode={() => setTab("code")}
            />
          </TabsContent>
          <TabsContent value="code" className="flex min-h-0 flex-1 flex-col overflow-hidden pt-0">
            <CodeTab
              path={`${detail.path}/agent.py`}
              code={code}
              onChange={(value) => {
                setCode(value);
                if (codeError) setCodeError(null);
              }}
              onSave={() => void saveCode()}
              readOnlyReason={codeReadOnlyReason}
              sourceMode={detail.source_mode}
              error={codeError}
            />
          </TabsContent>
          <TabsContent value="versions" className="min-h-0 flex-1 overflow-y-auto pt-0">
            <VersionsTab
              projectId={projectId}
              member={detail}
              canBuild={canBuild}
              dirty={dirty}
              onRestored={(next) => {
                adopt(next, { config: true, code: true });
                afterSave(next);
                void qc.invalidateQueries({ queryKey: studioKeys.versions(projectId, name) });
              }}
            />
          </TabsContent>
          <TabsContent value="evals" className="min-h-0 flex-1 overflow-y-auto pt-0">
            <EvalsTab projectId={projectId} member={detail.name} canBuild={canBuild} />
          </TabsContent>
          <TabsContent value="guard" className="min-h-0 flex-1 overflow-y-auto pt-0">
            <GuardPanel projectId={projectId} member={detail.name} canBuild={canBuild} />
          </TabsContent>
        </Tabs>
      </section>

      <section className="flex min-h-[38rem] flex-1 flex-col lg:min-h-0" aria-label={t("playgroundLabel")}>
        <Playground projectId={projectId} member={detail.name} canChat={canBuild} unsavedChanges={dirty} />
      </section>

      <ConfirmDialog
        open={guard.pendingHref !== null}
        onOpenChange={(open) => {
          if (!open) guard.clear();
        }}
        title={t("leaveTitle")}
        description={t("leaveDescription")}
        confirmLabel={t("leave")}
        cancelLabel={tc("cancel")}
        onConfirm={() => {
          const href = guard.pendingHref;
          guard.clear();
          if (href) router.push(href);
        }}
      />
    </div>
  );
}
