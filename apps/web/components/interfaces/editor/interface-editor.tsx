"use client";

import {
  Alert,
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Kbd,
  Skeleton,
  Tabs,
  TabsList,
  TabsTrigger,
  cn,
  toast,
} from "@messer/ui";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Code2, Eye, FileX, History, LayoutGrid, Plus, Save, Share2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { CodeEditor } from "@/components/studio/monaco";
import { ApiError, http } from "@/lib/api";
import { useRole } from "@/lib/hooks/use-me";
import { isNotFound, useMembers, useUnsavedChangesGuard } from "@/lib/studio/hooks";

import { interfaceKeys, useInterface, useKnowledgeBases } from "../api";
import { useDataLabels } from "../labels";
import { ComponentView } from "../renderer/component-view";
import { InterfaceRenderer } from "../renderer/interface-renderer";
import { previewSource } from "../source";
import { themeClass, themeStyle } from "../theme";
import type { ComponentDef, ComponentType, InterfaceDefinition, InterfaceDetail, Issue } from "../types";
import { messageOf } from "../util";
import type { BindingContext } from "./binding-editor";
import { GridCanvas } from "./canvas";
import {
  DEFAULT_SIZE,
  changedComponents,
  componentOfPath,
  defaultComponent,
  findComponent,
  findSpot,
  mapComponent,
  mapScreen,
  nextComponentId,
  nextScreenId,
  resolveCollisions,
} from "./model";
import { Palette } from "./palette";
import { ComponentProperties, InterfaceSettings } from "./properties-panel";
import { PublishButton } from "./publish-button";
import { ShareDialog } from "./share-dialog";
import { VersionsDialog } from "./versions-dialog";

type Mode = "design" | "preview" | "code";

function same(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = React.useState(value);
  React.useEffect(() => {
    const id = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(id);
  }, [value, ms]);
  return v;
}

export function InterfaceEditor({ projectId, interfaceId }: { projectId: string; interfaceId: string }) {
  const t = useTranslations("interfaces");
  const tc = useTranslations("common");
  const router = useRouter();
  const qc = useQueryClient();
  const canBuild = useRole("builder");
  const detail = useInterface(interfaceId);
  const agents = useMembers(projectId, "agent");
  const workflows = useMembers(projectId, "workflow");
  const kbs = useKnowledgeBases(projectId);
  const labels = useDataLabels();
  const source = React.useMemo(() => previewSource(interfaceId), [interfaceId]);

  const [saved, setSaved] = React.useState<InterfaceDefinition | null>(null);
  const [draft, setDraft] = React.useState<InterfaceDefinition | null>(null);
  const [mode, setMode] = React.useState<Mode>("design");
  const [screenId, setScreenId] = React.useState<string>("");
  const [selected, setSelected] = React.useState<string | null>(null);
  const [issues, setIssues] = React.useState<Issue[]>([]);
  const [warnings, setWarnings] = React.useState<Issue[]>([]);
  const [saving, setSaving] = React.useState(false);
  const [deleting, setDeleting] = React.useState<string | null>(null);
  const [deletingScreen, setDeletingScreen] = React.useState<string | null>(null);
  const [versionsOpen, setVersionsOpen] = React.useState(false);
  const [shareOpen, setShareOpen] = React.useState(false);
  const [codeText, setCodeText] = React.useState("");
  const [codeError, setCodeError] = React.useState<string | null>(null);

  const dirty = draft !== null && saved !== null && !same(draft, saved);
  const guard = useUnsavedChangesGuard(dirty);

  const load = React.useCallback((d: InterfaceDetail) => {
    setSaved(d.definition);
    setDraft(d.definition);
    setIssues(d.issues);
    setWarnings(d.warnings);
    setScreenId((s) => (d.definition.screens.some((x) => x.id === s) ? s : (d.definition.screens[0]?.id ?? "")));
  }, []);

  React.useEffect(() => {
    if (detail.data && (saved === null || !dirty)) load(detail.data);
    // Only when the server copy changes (new commit or first load).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail.data?.commit, detail.data?.updated_at]);

  React.useEffect(() => {
    if (!canBuild) setMode("preview");
  }, [canBuild]);

  // Live validation (structure, SQL, references) against the server, debounced.
  const debouncedDraft = useDebounced(draft, 700);
  React.useEffect(() => {
    if (!debouncedDraft || !canBuild) return;
    if (saved && same(debouncedDraft, saved)) {
      if (detail.data) {
        setIssues(detail.data.issues);
        setWarnings(detail.data.warnings);
      }
      return;
    }
    let cancelled = false;
    http
      .post<{ valid: boolean; issues: Issue[]; warnings: Issue[] }>(`/projects/${projectId}/interfaces/validate`, {
        definition: { ...debouncedDraft },
      })
      .then((res) => {
        if (cancelled) return;
        setIssues(res.issues);
        setWarnings(res.warnings);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [debouncedDraft, canBuild, projectId, saved, detail.data]);

  const save = React.useCallback(async (): Promise<boolean> => {
    if (!draft) return false;
    setSaving(true);
    try {
      const res = await http.put<InterfaceDetail>(`/interfaces/${interfaceId}`, {
        definition: { ...draft },
      });
      qc.setQueryData(interfaceKeys.detail(interfaceId), res);
      void qc.invalidateQueries({ queryKey: interfaceKeys.list(projectId) });
      void qc.invalidateQueries({ queryKey: interfaceKeys.versions(interfaceId) });
      load(res);
      toast.success(t("editor.saved"));
      return true;
    } catch (err) {
      if (err instanceof ApiError && Array.isArray(err.details.issues)) {
        setIssues(err.details.issues as Issue[]);
        toast.error(t("editor.saveInvalid", { count: (err.details.issues as Issue[]).length }));
      } else {
        toast.error(messageOf(err, tc("errorGeneric")));
      }
      return false;
    } finally {
      setSaving(false);
    }
  }, [draft, interfaceId, projectId, qc, load, t, tc]);

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (dirty && canBuild && !saving) void save();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dirty, canBuild, saving, save]);

  React.useEffect(() => {
    if (mode === "code" && draft) {
      setCodeText(JSON.stringify(draft, null, 2));
      setCodeError(null);
    }
    // Refresh the code view when entering it, not on every keystroke inside it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  const drafts = React.useMemo(() => (draft ? changedComponents(saved, draft) : {}), [saved, draft]);
  const issuesByComponent = React.useMemo(() => {
    const out: Record<string, number> = {};
    if (!draft) return out;
    for (const i of issues) {
      const id = componentOfPath(draft, i.path);
      if (id) out[id] = (out[id] ?? 0) + 1;
    }
    return out;
  }, [issues, draft]);

  if (detail.error) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-10">
        {isNotFound(detail.error) ? (
          <EmptyState
            icon={<FileX />}
            title={t("editor.notFound")}
            action={
              <Button asChild variant="secondary">
                <Link href={`/app/projects/${projectId}/interfaces`}>{t("editor.back")}</Link>
              </Button>
            }
          />
        ) : (
          <ErrorState title={tc("errorTitle")} description={messageOf(detail.error, tc("errorGeneric"))} onRetry={() => void detail.refetch()} retryLabel={tc("retry")} />
        )}
      </div>
    );
  }

  if (!detail.data || !draft) {
    return (
      <div className="flex flex-1 flex-col gap-3 p-4" role="status" aria-label={tc("loading")}>
        <Skeleton className="h-9 w-full" />
        <div className="flex flex-1 gap-3">
          <Skeleton className="hidden h-96 w-52 md:block" />
          <Skeleton className="h-96 flex-1" />
          <Skeleton className="hidden h-96 w-80 lg:block" />
        </div>
      </div>
    );
  }

  const info = detail.data;
  const screen = draft.screens.find((s) => s.id === screenId) ?? draft.screens[0];
  const selectedComp = findComponent(draft, selected);
  const ctx: BindingContext = {
    agents: (agents.data ?? []).map((m) => m.name),
    workflows: (workflows.data ?? []).map((m) => m.name),
    kbs: kbs.data ?? [],
  };
  const defaults = {
    agents: ctx.agents,
    workflows: ctx.workflows,
    kbIds: ctx.kbs.map((k) => k.id),
    label: t("editor.defaultButton"),
    fieldLabel: t("editor.defaultField"),
  };
  const rowHeight = draft.theme?.density === "compact" ? 44 : 56;
  const interfaceIssues = issues.filter((i) => !componentOfPath(draft, i.path));
  const selectedIssues = selected ? issues.filter((i) => componentOfPath(draft, i.path) === selected) : [];
  const selectedWarnings = selected ? warnings.filter((w) => componentOfPath(draft, w.path) === selected) : [];

  const addComponent = (type: ComponentType, at?: { x: number; y: number }) => {
    if (!screen || draft.kind === "chat") return;
    const size = DEFAULT_SIZE[type];
    const id = nextComponentId(type, draft);
    const grid = at
      ? { x: Math.min(at.x, 12 - size.w), y: at.y, w: size.w, h: size.h }
      : findSpot(screen.components, size.w, size.h);
    const comp = defaultComponent(type, id, grid, { ...defaults, title: t(`types.${type}.name`) });
    setDraft(
      mapScreen(draft, screen.id, (s) => ({
        ...s,
        components: at ? resolveCollisions([...s.components, comp], id) : [...s.components, comp],
      })),
    );
    setSelected(id);
  };

  const updateComponent = (comp: ComponentDef) => setDraft(mapComponent(draft, comp.id, () => comp));
  const renameComponent = (from: string, to: string) => {
    setDraft(mapComponent(draft, from, (c) => ({ ...c, id: to })));
    setSelected(to);
  };
  const removeComponent = (id: string) => {
    setDraft({ ...draft, screens: draft.screens.map((s) => ({ ...s, components: s.components.filter((c) => c.id !== id) })) });
    if (selected === id) setSelected(null);
  };
  const addScreen = () => {
    const id = nextScreenId(draft);
    setDraft({ ...draft, screens: [...draft.screens, { id, title: t("editor.newScreen", { n: draft.screens.length + 1 }), layout: "grid", components: [] }] });
    setScreenId(id);
    setSelected(null);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2">
        <Button asChild variant="ghost" size="icon-sm" aria-label={t("editor.back")}>
          <Link href={`/app/projects/${projectId}/interfaces`}>
            <ArrowLeft />
          </Link>
        </Button>
        <div className="min-w-0">
          <h1 className="truncate text-base font-semibold text-fg">{draft.name}</h1>
          <p className="truncate font-mono text-xs text-fg-subtle">interfaces/{draft.slug}/interface.json</p>
        </div>
        <Badge>{t(`kinds.${draft.kind}`)}</Badge>
        {info.published ? <Badge tone="success">{t("list.published")}</Badge> : <Badge tone="outline">{t("list.draft")}</Badge>}
        {dirty ? <Badge tone="warning">{t("editor.unsaved")}</Badge> : null}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {canBuild ? (
            <Tabs value={mode} onValueChange={(v) => setMode(v as Mode)}>
              <TabsList aria-label={t("editor.mode")} className="border-b-0">
                <TabsTrigger value="design">
                  <LayoutGrid />
                  {t("editor.design")}
                </TabsTrigger>
                <TabsTrigger value="preview">
                  <Eye />
                  {t("editor.preview")}
                </TabsTrigger>
                <TabsTrigger value="code">
                  <Code2 />
                  {t("editor.code")}
                </TabsTrigger>
              </TabsList>
            </Tabs>
          ) : null}
          <Button variant="ghost" size="sm" onClick={() => setVersionsOpen(true)}>
            <History />
            {t("editor.versions")}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setShareOpen(true)}>
            <Share2 />
            {t("editor.share")}
          </Button>
          {canBuild ? (
            <Button variant="secondary" loading={saving} disabled={!dirty} onClick={() => void save()} title={t("editor.saveShortcut")}>
              <Save />
              {t("editor.save")}
              <Kbd className="ml-1 hidden lg:inline-flex">⌘S</Kbd>
            </Button>
          ) : null}
          <PublishButton projectId={projectId} interfaceId={interfaceId} dirty={dirty} canPublish={canBuild} onSaveFirst={save} />
        </div>
      </div>

      {mode === "design" && canBuild ? (
        <div className="flex min-h-0 flex-1">
          <aside className="hidden w-56 shrink-0 overflow-y-auto border-r border-border p-2 md:block">
            {draft.kind === "chat" ? <p className="p-2 text-xs text-fg-muted">{t("editor.chatOnly")}</p> : <Palette onAdd={(type) => addComponent(type)} />}
          </aside>
          <main className="min-w-0 flex-1 overflow-auto bg-bg p-4">
            {draft.kind === "app" ? (
              <div className="mb-3 flex items-center gap-1 overflow-x-auto">
                <Tabs value={screen?.id ?? ""} onValueChange={(v) => { setScreenId(v); setSelected(null); }}>
                  <TabsList aria-label={t("renderer.screens")}>
                    {draft.screens.map((s) => (
                      <TabsTrigger key={s.id} value={s.id}>
                        {s.title}
                      </TabsTrigger>
                    ))}
                  </TabsList>
                </Tabs>
                <Button size="icon-sm" variant="ghost" aria-label={t("settings.addScreen")} onClick={addScreen}>
                  <Plus />
                </Button>
              </div>
            ) : null}
            {screen && screen.components.length === 0 ? (
              <p className="mb-3 rounded-md border border-dashed border-border-strong px-4 py-3 text-sm text-fg-muted">{t("editor.emptyCanvas")}</p>
            ) : null}
            {screen ? (
              <div className={cn(themeClass(draft.theme))} style={themeStyle(draft.theme)}>
                <GridCanvas
                  components={screen.components}
                  selectedId={selected}
                  rowHeight={rowHeight}
                  issues={issuesByComponent}
                  onSelect={setSelected}
                  onChange={(components) => setDraft(mapScreen(draft, screen.id, (s) => ({ ...s, components })))}
                  onDropNew={(type, at) => addComponent(type, at)}
                  onDelete={(id) => setDeleting(id)}
                  renderTile={(comp) => (
                    <div className="flex h-full flex-col p-2">
                      <ComponentView comp={comp} source={source} labels={labels} draft={drafts[comp.id] ?? null} bare />
                    </div>
                  )}
                />
              </div>
            ) : null}
          </main>
          <aside className="w-80 shrink-0 overflow-y-auto border-l border-border" aria-label={t("editor.properties")}>
            {selectedComp ? (
              <>
                {selectedWarnings.length > 0 ? (
                  <div className="px-3 pt-3">
                    <Alert tone="warning">
                      <ul className="text-xs">
                        {selectedWarnings.map((w, i) => (
                          <li key={i}>{w.message}</li>
                        ))}
                      </ul>
                    </Alert>
                  </div>
                ) : null}
                <ComponentProperties
                  key={selectedComp.id}
                  comp={selectedComp}
                  ctx={ctx}
                  issues={selectedIssues}
                  idTaken={(id) => findComponent(draft, id) !== null}
                  onChange={updateComponent}
                  onRename={(id) => renameComponent(selectedComp.id, id)}
                  onDelete={() => setDeleting(selectedComp.id)}
                />
              </>
            ) : (
              <InterfaceSettings
                definition={draft}
                issues={interfaceIssues}
                onChange={setDraft}
                onAddScreen={addScreen}
                onDeleteScreen={(id) => setDeletingScreen(id)}
                activeScreen={screen?.id ?? ""}
              />
            )}
          </aside>
        </div>
      ) : null}

      {mode === "preview" ? (
        <div className="min-h-0 flex-1 overflow-auto">
          <div className={cn("min-h-full bg-bg p-4 md:p-6", themeClass(draft.theme))} style={themeStyle(draft.theme)}>
            <div className="mb-3 flex items-center gap-2 text-xs text-fg-muted">
              <Badge tone="info">{t("editor.previewBadge")}</Badge>
              {t("editor.previewHint")}
            </div>
            <InterfaceRenderer definition={draft} source={source} drafts={drafts} />
          </div>
        </div>
      ) : null}

      {mode === "code" && canBuild ? (
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="min-h-0 flex-1">
            <CodeEditor
              value={codeText}
              language="json"
              ariaLabel={t("editor.code")}
              onSave={() => void save()}
              onChange={(text) => {
                setCodeText(text);
                try {
                  const parsed = JSON.parse(text) as unknown;
                  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("shape");
                  setCodeError(null);
                  setDraft(parsed as InterfaceDefinition);
                } catch (err) {
                  setCodeError(err instanceof Error && err.message !== "shape" ? err.message : t("editor.codeObject"));
                }
              }}
            />
          </div>
          {codeError || issues.length > 0 ? (
            <div className="max-h-44 overflow-auto border-t border-border px-4 py-2 text-xs" role="status">
              {codeError ? <p className="text-danger">{t("editor.codeInvalidJson", { error: codeError })}</p> : null}
              <ul className="flex flex-col gap-0.5">
                {issues.map((i, n) => (
                  <li key={n} className="text-danger">
                    <span className="font-mono">{i.path}</span> — {i.message}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => (open ? undefined : setDeleting(null))}
        title={t("editor.deleteComponentTitle")}
        description={t("editor.deleteComponentDescription", { id: deleting ?? "" })}
        confirmLabel={tc("delete")}
        cancelLabel={tc("cancel")}
        onConfirm={() => {
          if (deleting) removeComponent(deleting);
          setDeleting(null);
        }}
      />
      <ConfirmDialog
        open={deletingScreen !== null}
        onOpenChange={(open) => (open ? undefined : setDeletingScreen(null))}
        title={t("settings.deleteScreenTitle")}
        description={t("settings.deleteScreenDescription")}
        confirmLabel={tc("delete")}
        cancelLabel={tc("cancel")}
        onConfirm={() => {
          if (deletingScreen && draft.screens.length > 1) {
            const rest = draft.screens.filter((s) => s.id !== deletingScreen);
            setDraft({ ...draft, screens: rest });
            setScreenId(rest[0]?.id ?? "");
          }
          setDeletingScreen(null);
        }}
      />
      <ConfirmDialog
        open={guard.pendingHref !== null}
        onOpenChange={(open) => (open ? undefined : guard.clear())}
        title={t("editor.leaveTitle")}
        description={t("editor.leaveDescription")}
        confirmLabel={t("editor.leave")}
        cancelLabel={tc("cancel")}
        onConfirm={() => {
          const href = guard.pendingHref;
          guard.clear();
          if (href) router.push(href);
        }}
      />
      <VersionsDialog
        open={versionsOpen}
        onOpenChange={setVersionsOpen}
        interfaceId={interfaceId}
        current={draft}
        canRestore={canBuild}
        onRestored={(d) => {
          qc.setQueryData(interfaceKeys.detail(interfaceId), d);
          load(d);
        }}
      />
      <ShareDialog open={shareOpen} onOpenChange={setShareOpen} urls={info.urls} published={info.published} kind={draft.kind} />
    </div>
  );
}
