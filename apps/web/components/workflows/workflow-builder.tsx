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
import { ReactFlowProvider } from "@xyflow/react";
import { AlertTriangle, ArrowLeft, Code2, History, Play, Puzzle, Save, Undo2, Workflow, Zap } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { VersionsTab } from "@/components/studio/builder/versions-tab";
import { ApiError, http } from "@/lib/api";
import { useRole } from "@/lib/hooks/use-me";
import { errorMessage, isNotFound, studioKeys, useUnsavedChangesGuard } from "@/lib/studio/hooks";
import type { MemberDetail } from "@/lib/studio/types";
import { type Issue, isValidId, renameNode, removeNodes, validateGraph } from "@/lib/workflows/graph";
import { useHistory } from "@/lib/workflows/history";
import { usePalette, useWorkflow, workflowKeys, workflowPath } from "@/lib/workflows/hooks";
import type { CustomNodes, Position, ValidationIssue, Viewport, WorkflowConfig, WorkflowDetail, WorkflowNode } from "@/lib/workflows/types";
import { useWorkflowRun } from "@/lib/workflows/use-run";

import { CustomNodesTab } from "./code/custom-nodes-tab";
import { type CodeProblem, WorkflowCodeTab } from "./code/workflow-code-tab";
import { EngineFlow } from "./canvas/engine-flow";
import { WorkflowCanvas, edgeId } from "./canvas/workflow-canvas";
import { NodePanel, type PanelIssue } from "./panel/node-panel";
import { type ListedIssue, WorkflowPanel } from "./panel/workflow-panel";
import { RunPanel } from "./run/run-panel";
import { TriggersTab } from "./triggers/triggers-tab";

type TabKey = "canvas" | "code" | "custom" | "triggers" | "versions";

function semantic(doc: WorkflowConfig): string {
  return JSON.stringify({ ...doc, nodes: doc.nodes.map((n) => ({ ...n, position: undefined })) });
}

function layout(doc: WorkflowConfig): string {
  return JSON.stringify(doc.nodes.map((n) => [n.id, Math.round(n.position?.x ?? 0), Math.round(n.position?.y ?? 0)]));
}

function withPositions(detail: WorkflowDetail): WorkflowConfig | null {
  if (!detail.config) return null;
  return {
    ...detail.config,
    nodes: detail.config.nodes.map((n) => ({ ...n, position: n.position ?? detail.positions[n.id] ?? { x: 0, y: 0 } })),
  };
}

function DirtyDot({ label }: { label: string }) {
  return (
    <span className="inline-flex" title={label}>
      <StatusDot tone="warning" />
      <span className="sr-only">{label}</span>
    </span>
  );
}

export function WorkflowBuilder({ projectId, name }: { projectId: string; name: string }) {
  const t = useTranslations("workflows");
  const tc = useTranslations("common");
  const router = useRouter();
  const qc = useQueryClient();
  const canBuild = useRole("builder");
  const detailQuery = useWorkflow(projectId, name);
  const palette = usePalette(projectId);
  const history = useHistory<WorkflowConfig>();
  const doc = history.present;

  const [tab, setTab] = React.useState<TabKey>("canvas");
  const [saved, setSaved] = React.useState<WorkflowConfig | null>(null);
  const [code, setCode] = React.useState<string | null>(null);
  const [codeSaved, setCodeSaved] = React.useState<string | null>(null);
  const [codeProblem, setCodeProblem] = React.useState<CodeProblem | null>(null);
  const [customNodes, setCustomNodes] = React.useState<CustomNodes | null>(null);
  const [customDirty, setCustomDirty] = React.useState(false);
  const [serverIssues, setServerIssues] = React.useState<ValidationIssue[]>([]);
  const [selected, setSelected] = React.useState<string[]>([]);
  const [viewport, setViewport] = React.useState<Viewport>({ x: 0, y: 0, zoom: 1 });
  const [runOpen, setRunOpen] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const lastEdit = React.useRef<{ key: string; at: number } | null>(null);
  const savedRef = React.useRef<WorkflowConfig | null>(null);
  const codeSavedRef = React.useRef<string | null>(null);
  const initialised = React.useRef(false);

  const adopt = React.useCallback(
    (detail: WorkflowDetail, force: { graph: boolean; code: boolean }) => {
      const server = withPositions(detail);
      const prevSaved = savedRef.current;
      savedRef.current = server;
      setSaved(server);
      if (server && (force.graph || !history.present || !prevSaved || semantic(history.present) === semantic(prevSaved))) {
        history.reset(server);
      }
      const prevCode = codeSavedRef.current;
      codeSavedRef.current = detail.code;
      setCodeSaved(detail.code);
      setCode((prev) => (force.code || prev === null || prev === prevCode ? detail.code : prev));
      setCustomNodes(detail.custom_nodes);
      setViewport(detail.viewport);
    },
    [history],
  );

  React.useEffect(() => {
    if (!detailQuery.data) return;
    adopt(detailQuery.data, { graph: false, code: false });
    if (!initialised.current) {
      initialised.current = true;
      if (detailQuery.data.source_mode === "code") setTab("code");
    }
    // `adopt` is stable for a given history instance; re-adopting on every render would discard edits.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detailQuery.data]);

  const detail = detailQuery.data;
  const codeMode = detail?.source_mode === "code";
  const graphDirty = Boolean(doc && saved && (semantic(doc) !== semantic(saved) || layout(doc) !== layout(saved)));
  const graphSemanticDirty = Boolean(doc && saved && semantic(doc) !== semantic(saved));
  const codeDirty = code !== null && codeSaved !== null && code !== codeSaved;
  const dirty = graphDirty || codeDirty || customDirty;
  const guard = useUnsavedChangesGuard(dirty);
  const graphReadOnly = !canBuild || codeMode || codeDirty;
  const functions = React.useMemo(() => customNodes?.functions ?? [], [customNodes]);

  // --------------------------------------------------------------------------------------- validation

  const toolParams = React.useMemo(
    () => (palette.data ? Object.fromEntries(palette.data.tools.map((x) => [x.key, x.params])) : undefined),
    [palette.data],
  );
  const clientIssues = React.useMemo<Issue[]>(() => {
    if (!doc || !palette.data) return [];
    return validateGraph(doc, {
      agents: palette.data.agents.map((a) => a.name),
      workflows: palette.data.workflows.map((w) => w.name).filter((w) => w !== doc.name),
      functions: functions.map((f) => f.name),
      toolParams,
      maxWait: palette.data.limits.max_wait_seconds,
    });
  }, [doc, palette.data, functions, toolParams]);
  const issueText = React.useCallback(
    (issue: Issue): string => (issue.message ? issue.message : t(`issues.${issue.code}`, issue.params ?? {})),
    [t],
  );
  const allIssues = React.useMemo<Issue[]>(() => [...clientIssues, ...serverIssues], [clientIssues, serverIssues]);
  const issuesByNode = React.useMemo(() => {
    const map = new Map<string, string[]>();
    for (const issue of allIssues) {
      if (!issue.node_id) continue;
      map.set(issue.node_id, [...(map.get(issue.node_id) ?? []), issueText(issue)]);
    }
    return map;
  }, [allIssues, issueText]);
  const issueEdges = React.useMemo(
    () => new Set(allIssues.filter((i) => i.edge).map((i) => edgeId({ source: i.edge?.source ?? "", target: i.edge?.target ?? "" }))),
    [allIssues],
  );
  const listedIssues = React.useMemo<ListedIssue[]>(
    () => allIssues.map((issue, i) => ({ key: `${issue.code}-${issue.node_id ?? ""}-${i}`, message: issueText(issue), nodeId: issue.node_id })),
    [allIssues, issueText],
  );
  const hasErrors = clientIssues.length > 0;

  // ---------------------------------------------------------------------------------------- run state

  const knownIds = React.useMemo(() => {
    if (doc) return new Set(doc.nodes.map((n) => n.id));
    return new Set((detail?.flow?.nodes ?? []).map((n) => n.id.split(".").slice(1).join(".") || n.id));
  }, [doc, detail?.flow]);
  const runner = useWorkflowRun(projectId, name, knownIds, tc("errorGeneric"));
  const runActive = runOpen && runner.state.phase !== "idle";

  // ------------------------------------------------------------------------------------------- edits

  const record = (key: string) => {
    const now = Date.now();
    const coalesce = lastEdit.current !== null && lastEdit.current.key === key && now - lastEdit.current.at < 1000;
    lastEdit.current = { key, at: now };
    return !coalesce;
  };

  const changeDoc = (key: string, update: (d: WorkflowConfig) => WorkflowConfig) => {
    setServerIssues([]);
    history.set(update, { record: record(key) });
  };

  const updateNode = (id: string, update: (n: WorkflowNode) => WorkflowNode, key: string) =>
    changeDoc(`${id}:${key}`, (d) => ({ ...d, nodes: d.nodes.map((n) => (n.id === id ? update(n) : n)) }));

  const onConfig = (node: WorkflowNode, patch: Record<string, unknown>, field: string) => {
    if (node.type === "loop" && "body" in patch) {
      const body = String(patch.body ?? "");
      changeDoc(`${node.id}:body`, (d) => {
        const previous = String(d.nodes.find((n) => n.id === node.id)?.config.body ?? "");
        const edges = d.edges.filter((e) => !(e.source === node.id && e.target === previous) && !(e.source === previous && e.target === node.id));
        const cleaned = body ? edges.filter((e) => e.source !== body && e.target !== body) : edges;
        return {
          ...d,
          nodes: d.nodes.map((n) => (n.id === node.id ? { ...n, config: { ...n.config, body } } : n)),
          edges: body ? [...cleaned, { source: node.id, target: body }] : cleaned,
        };
      });
      return;
    }
    updateNode(node.id, (n) => ({ ...n, config: { ...n.config, ...patch } }), `config.${field}`);
  };

  const rename = (oldId: string, newId: string): string | null => {
    if (!doc) return null;
    if (!isValidId(newId)) return t("panel.idInvalid");
    if (doc.nodes.some((n) => n.id === newId)) return t("panel.idTaken");
    changeDoc(`rename:${oldId}`, (d) => renameNode(d, oldId, newId));
    setSelected((s) => s.map((id) => (id === oldId ? newId : id)));
    return null;
  };

  // -------------------------------------------------------------------------------------------- saves

  const afterSave = (next: WorkflowDetail) => {
    qc.setQueryData(workflowKeys.detail(projectId, name), next);
    void qc.invalidateQueries({ queryKey: workflowKeys.list(projectId) });
    void qc.invalidateQueries({ queryKey: studioKeys.members(projectId) });
    void qc.invalidateQueries({ queryKey: studioKeys.versions(projectId, name) });
  };

  const saveGraph = async () => {
    if (!doc || saving) return;
    if (hasErrors) {
      setTab("canvas");
      setSelected([]);
      setRunOpen(false);
      toast.error(t("builder.fixErrors"));
      return;
    }
    setSaving(true);
    try {
      let next: WorkflowDetail;
      if (!graphSemanticDirty) {
        const positions = Object.fromEntries(doc.nodes.map((n) => [n.id, n.position ?? { x: 0, y: 0 }]));
        await http.put(`${workflowPath(projectId, name)}/layout`, { positions, viewport } as unknown as Record<string, unknown>);
        next = await http.get<WorkflowDetail>(workflowPath(projectId, name));
      } else {
        next = await http.put<WorkflowDetail>(`${workflowPath(projectId, name)}/graph`, { config: doc, viewport } as unknown as Record<string, unknown>);
      }
      adopt(next, { graph: true, code: true });
      afterSave(next);
      setServerIssues([]);
      toast.success(t("builder.saved"));
    } catch (err) {
      if (err instanceof ApiError && err.code === "invalid_workflow" && Array.isArray(err.details.issues)) {
        setServerIssues(err.details.issues as ValidationIssue[]);
        setTab("canvas");
        setSelected([]);
        setRunOpen(false);
      }
      toast.error(errorMessage(err, tc("errorGeneric")));
    } finally {
      setSaving(false);
    }
  };

  const saveCode = async () => {
    if (code === null || saving) return;
    setSaving(true);
    setCodeProblem(null);
    try {
      const next = await http.put<WorkflowDetail>(`${workflowPath(projectId, name)}/code`, { code });
      adopt(next, { graph: true, code: true });
      afterSave(next);
      toast.success(next.source_mode === "code" ? t("builder.codeSavedCodeMode") : t("builder.codeSaved"));
    } catch (err) {
      if (err instanceof ApiError && err.code === "syntax_error") {
        setCodeProblem({
          message: err.message,
          line: typeof err.details.line === "number" ? err.details.line : null,
          column: typeof err.details.column === "number" ? err.details.column : null,
        });
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
    else if (graphDirty) void saveGraph();
  };
  const discard = () => {
    if (saved) history.reset(saved);
    if (codeSaved !== null) setCode(codeSaved);
    setCodeProblem(null);
    setServerIssues([]);
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

  const arrange = async (positions: Record<string, Position>) => {
    if (!canBuild) return;
    try {
      await http.put(`${workflowPath(projectId, name)}/layout`, { positions } as unknown as Record<string, unknown>);
    } catch (err) {
      toast.error(errorMessage(err, tc("errorGeneric")));
    }
  };

  // ------------------------------------------------------------------------------------------- render

  if (detailQuery.isLoading || palette.isLoading || (detail && code === null)) {
    return (
      <div className="grid gap-6 p-6 lg:grid-cols-[15rem_1fr_22rem]">
        <SkeletonRows rows={8} />
        <SkeletonRows rows={12} />
        <SkeletonRows rows={8} />
      </div>
    );
  }
  if (detailQuery.error || palette.error || !detail || !palette.data || code === null) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-10">
        {isNotFound(detailQuery.error) ? (
          <EmptyState
            icon={<Workflow />}
            title={t("builder.notFound.title")}
            description={t("builder.notFound.description", { name })}
            action={
              <Button asChild variant="secondary">
                <Link href={`/app/projects/${projectId}/workflows`}>{t("builder.notFound.back")}</Link>
              </Button>
            }
          />
        ) : (
          <ErrorState
            title={tc("errorTitle")}
            description={errorMessage(detailQuery.error ?? palette.error, tc("errorGeneric"))}
            onRetry={() => {
              void detailQuery.refetch();
              void palette.refetch();
            }}
            retryLabel={tc("retry")}
          />
        )}
      </div>
    );
  }

  const paletteData = palette.data;
  const selectedNode = doc && selected.length === 1 ? doc.nodes.find((n) => n.id === selected[0]) ?? null : null;
  const nodePanelIssues: PanelIssue[] = selectedNode
    ? allIssues.filter((i) => i.node_id === selectedNode.id).map((i) => ({ field: i.field, message: issueText(i) }))
    : [];
  const usedBy: Record<string, string[]> = {};
  for (const n of doc?.nodes ?? []) {
    if (n.type === "custom" && typeof n.config.function === "string") usedBy[n.config.function] = [...(usedBy[n.config.function] ?? []), n.id];
  }
  const memberForVersions = {
    id: detail.id,
    name: detail.name,
    kind: "workflow",
    description: detail.description,
    path: detail.path,
    source_mode: detail.source_mode,
    current_version: detail.current_version,
    guard_enabled: false,
    updated_at: detail.updated_at,
    config: {},
    code: detail.code,
    commit: detail.commit,
  } satisfies MemberDetail;

  const tabLabel = (key: TabKey, Icon: typeof Code2, label: string, isDirty = false) => (
    <TabsTrigger value={key}>
      <Icon aria-hidden />
      {label}
      {isDirty ? <DirtyDot label={t("builder.unsaved")} /> : null}
    </TabsTrigger>
  );

  let rightPanel: React.ReactNode = null;
  if (runOpen) {
    rightPanel = (
      <RunPanel
        projectId={projectId}
        config={doc}
        run={runner.state}
        busy={runner.busy}
        deciding={runner.deciding}
        canRun={canBuild}
        dirty={dirty}
        selectedNode={selected.length === 1 ? (selected[0] ?? null) : null}
        onSelectNode={(id) => setSelected(id ? [id] : [])}
        onRun={(input, event) => void runner.start(input, event)}
        onStop={runner.stop}
        onReset={runner.reset}
        onDecide={(id, body) => void runner.decide(id, body)}
        onClose={() => setRunOpen(false)}
      />
    );
  } else if (doc && selectedNode) {
    rightPanel = (
      <NodePanel
        key={selectedNode.id}
        projectId={projectId}
        node={selectedNode}
        doc={doc}
        palette={paletteData}
        functions={functions}
        issues={nodePanelIssues}
        readOnly={graphReadOnly}
        onConfig={(patch, field) => onConfig(selectedNode, patch, field)}
        onLabel={(label) => updateNode(selectedNode.id, (n) => ({ ...n, label }), "label")}
        onRename={(id) => rename(selectedNode.id, id)}
        onInputs={(inputs) => changeDoc("inputs", (d) => ({ ...d, inputs }))}
        onDelete={() => {
          changeDoc(`delete:${selectedNode.id}`, (d) => removeNodes(d, new Set([selectedNode.id])));
          setSelected([]);
        }}
        onClose={() => setSelected([])}
        onOpenCustomNodes={() => setTab("custom")}
      />
    );
  } else if (doc) {
    rightPanel = (
      <WorkflowPanel
        doc={doc}
        issues={listedIssues}
        readOnly={graphReadOnly}
        onDescription={(description) => changeDoc("description", (d) => ({ ...d, description }))}
        onInputs={(inputs) => changeDoc("inputs", (d) => ({ ...d, inputs }))}
        onSelectNode={(id) => setSelected([id])}
      />
    );
  }

  return (
    <div className="flex flex-col lg:h-[calc(100dvh-8rem-1px)]">
      <div className="flex flex-wrap items-start gap-3 border-b border-border px-4 py-3 md:px-5">
        <Button asChild variant="ghost" size="icon-sm" aria-label={t("builder.back")}>
          <Link href={`/app/projects/${projectId}/workflows`}>
            <ArrowLeft />
          </Link>
        </Button>
        <div className="min-w-0 flex-1">
          <h1 className="flex flex-wrap items-center gap-2 text-base font-semibold">
            <span className="font-mono">{detail.name}</span>
            <Badge tone="outline">v{detail.current_version}</Badge>
            {codeMode ? <Badge tone="info">{t("builder.codeModeBadge")}</Badge> : null}
            {allIssues.length ? (
              <Badge tone="danger">
                <AlertTriangle className="size-3" aria-hidden />
                {t("builder.issues", { n: allIssues.length })}
              </Badge>
            ) : null}
            {dirty ? (
              <Badge tone="warning">
                <StatusDot tone="warning" />
                {t("builder.unsaved")}
              </Badge>
            ) : null}
          </h1>
          <p className="mt-0.5 truncate text-xs text-fg-muted">{detail.description || t("builder.noDescription")}</p>
        </div>
        <div className="flex items-center gap-2">
          {canBuild && (graphDirty || codeDirty) ? (
            <Button variant="ghost" size="sm" onClick={discard} disabled={saving}>
              <Undo2 />
              {t("builder.discard")}
            </Button>
          ) : null}
          {canBuild ? (
            <Button
              variant="secondary"
              size="sm"
              onClick={save}
              loading={saving}
              disabled={!(graphDirty || codeDirty) || (graphDirty && !codeDirty && hasErrors)}
              title={t("builder.saveShortcut")}
            >
              <Save />
              {codeDirty ? t("builder.saveCode") : t("builder.save")}
              <Kbd className="hidden xl:inline-flex">⌘S</Kbd>
            </Button>
          ) : null}
          <Button
            variant={runOpen ? "dark" : "primary"}
            size="sm"
            onClick={() => {
              setTab("canvas");
              setRunOpen((o) => !o);
            }}
            aria-pressed={runOpen}
          >
            <Play />
            {t("builder.run")}
          </Button>
        </div>
      </div>

      <Tabs value={tab} onValueChange={(v) => setTab(v as TabKey)} className="flex min-h-0 flex-1 flex-col">
        <TabsList className="px-3 md:px-4">
          {tabLabel("canvas", Workflow, t("builder.tabs.canvas"), graphDirty)}
          {tabLabel("code", Code2, t("builder.tabs.code"), codeDirty)}
          {tabLabel("custom", Puzzle, t("builder.tabs.custom"), customDirty)}
          {tabLabel("triggers", Zap, t("builder.tabs.triggers"))}
          {tabLabel("versions", History, t("builder.tabs.versions"))}
        </TabsList>
        <TabsContent value="canvas" className="flex min-h-[36rem] flex-1 flex-col pt-0 lg:min-h-0">
          {codeMode ? (
            <div className="border-b border-border px-4 py-2">
              <Alert
                tone="info"
                title={t("canvas.codeModeTitle")}
                action={
                  <Button size="sm" variant="secondary" onClick={() => setTab("code")}>
                    {t("canvas.codeModeOpenCode")}
                  </Button>
                }
              >
                {t("canvas.codeModeDescription")}
              </Alert>
            </div>
          ) : codeDirty ? (
            <div className="border-b border-border px-4 py-2">
              <Alert tone="warning">{t("canvas.codeDirty")}</Alert>
            </div>
          ) : !canBuild ? (
            <div className="border-b border-border px-4 py-2">
              <Alert tone="info">{t("canvas.readOnlyViewer")}</Alert>
            </div>
          ) : null}
          <div className="flex min-h-0 flex-1">
            <ReactFlowProvider>
              {doc && !codeMode ? (
                <WorkflowCanvas
                  doc={doc}
                  history={history}
                  palette={paletteData}
                  functions={functions}
                  selected={selected}
                  onSelect={setSelected}
                  issuesByNode={issuesByNode}
                  issueEdges={issueEdges}
                  run={runActive ? runner.state : null}
                  readOnly={graphReadOnly}
                  viewport={viewport}
                  onViewportChange={setViewport}
                />
              ) : (
                <EngineFlow
                  flow={detail.flow}
                  error={detail.flow_error}
                  positions={detail.positions}
                  run={runActive ? runner.state : null}
                  canArrange={canBuild}
                  onArrange={(positions) => void arrange(positions)}
                  onSelect={(id) => setSelected(id ? [id] : [])}
                />
              )}
            </ReactFlowProvider>
            {rightPanel}
          </div>
        </TabsContent>
        <TabsContent value="code" className="flex min-h-0 flex-1 flex-col overflow-hidden pt-0">
          <WorkflowCodeTab
            path={`${detail.path}/workflow.py`}
            code={code}
            onChange={(value) => {
              setCode(value);
              if (codeProblem) setCodeProblem(null);
            }}
            onSave={() => void saveCode()}
            readOnlyReason={!canBuild ? "viewer" : graphDirty ? "graph_dirty" : null}
            codeMode={codeMode}
            problem={codeProblem}
          />
        </TabsContent>
        <TabsContent value="custom" className="flex min-h-0 flex-1 flex-col overflow-hidden pt-0" forceMount hidden={tab !== "custom"}>
          {customNodes ? (
            <CustomNodesTab
              projectId={projectId}
              workflow={name}
              path={`${detail.path}/nodes.py`}
              value={customNodes}
              canBuild={canBuild}
              usedBy={usedBy}
              onDirtyChange={setCustomDirty}
              onSaved={(next) => {
                setCustomNodes(next);
                void detailQuery.refetch();
              }}
            />
          ) : null}
        </TabsContent>
        <TabsContent value="triggers" className="min-h-0 flex-1 overflow-y-auto pt-0">
          <TriggersTab projectId={projectId} workflowId={detail.id} workflow={name} palette={paletteData} canBuild={canBuild} />
        </TabsContent>
        <TabsContent value="versions" className="min-h-0 flex-1 overflow-y-auto pt-0">
          <VersionsTab
            projectId={projectId}
            member={memberForVersions}
            canBuild={canBuild}
            dirty={dirty}
            onRestored={async () => {
              const next = await detailQuery.refetch();
              if (next.data) {
                adopt(next.data, { graph: true, code: true });
                afterSave(next.data);
              }
            }}
          />
        </TabsContent>
      </Tabs>

      <ConfirmDialog
        open={guard.pendingHref !== null}
        onOpenChange={(open) => {
          if (!open) guard.clear();
        }}
        title={t("builder.leaveTitle")}
        description={t("builder.leaveDescription")}
        confirmLabel={t("builder.leave")}
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
