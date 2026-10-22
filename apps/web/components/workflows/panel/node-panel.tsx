"use client";

import { Alert, Button, Checkbox, ConfirmDialog, Input, Select, Switch, Textarea } from "@messer/ui";
import { Code2, Plus, Trash2, X } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import * as React from "react";

import { bindingOptions } from "@/lib/workflows/bindings";
import { bodyOf, isValidId } from "@/lib/workflows/graph";
import { useConnectionActions } from "@/lib/workflows/hooks";
import type { CustomFunction, Palette, WorkflowConfig, WorkflowInput, WorkflowNode } from "@/lib/workflows/types";
import { LOOP_BODY_TYPES } from "@/lib/workflows/types";

import { NODE_ICONS } from "../node-meta";
import { InputsEditor } from "./inputs-editor";
import { FieldIssues, KeyValueEditor, PanelField, TemplateField, ValueEditor, asText } from "./fields";

export interface PanelIssue {
  field?: string;
  message: string;
}

type Config = Record<string, unknown>;

function str(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function obj(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function num(value: unknown, fallback: number): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

export function NodePanel({
  projectId,
  node,
  doc,
  palette,
  functions,
  issues,
  readOnly,
  onConfig,
  onLabel,
  onRename,
  onInputs,
  onDelete,
  onClose,
  onOpenCustomNodes,
}: {
  projectId: string;
  node: WorkflowNode;
  doc: WorkflowConfig;
  palette: Palette;
  functions: CustomFunction[];
  issues: PanelIssue[];
  readOnly: boolean;
  onConfig: (patch: Config, field: string) => void;
  onLabel: (label: string) => void;
  onRename: (id: string) => string | null;
  onInputs: (inputs: WorkflowInput[]) => void;
  onDelete: () => void;
  onClose: () => void;
  onOpenCustomNodes: () => void;
}) {
  const t = useTranslations("workflows");
  const tc = useTranslations("common");
  const [idDraft, setIdDraft] = React.useState(node.id);
  const [idError, setIdError] = React.useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = React.useState(false);
  React.useEffect(() => {
    setIdDraft(node.id);
    setIdError(null);
  }, [node.id]);

  const Icon = NODE_ICONS[node.type];
  const c = node.config;
  const options = React.useMemo(() => bindingOptions(doc, node.id), [doc, node.id]);
  const fieldIssues = (field: string) =>
    issues.filter((i) => i.field === field || (i.field ?? "").startsWith(`${field}.`)).map((i) => i.message);
  const generalIssues = issues.filter((i) => !i.field).map((i) => i.message);
  const fid = (field: string) => `wf-${node.id}-${field}`;
  const set = (field: string, value: unknown) => onConfig({ [field]: value }, field);
  const roleOptions = palette.roles.map((r) => ({ value: r, label: tc(`roles.${r}`) }));

  const commitId = () => {
    const next = idDraft.trim();
    if (next === node.id) return;
    if (!isValidId(next)) {
      setIdError(t("panel.idInvalid"));
      return;
    }
    const error = onRename(next);
    setIdError(error);
  };

  const roleField = (field = "approver_role") => (
    <PanelField label={t("panel.approverRole")} htmlFor={fid(field)} hint={t("panel.approverRoleHint")}>
      <Select
        id={fid(field)}
        value={str(c[field], "admin")}
        disabled={readOnly}
        onValueChange={(v) => set(field, v)}
        options={roleOptions}
      />
    </PanelField>
  );

  const approvalSwitch = (forced = false) => (
    <div className="space-y-2 rounded-md border border-border p-2.5">
      <label className="flex items-center justify-between gap-2 text-xs font-medium">
        {t("panel.requiresApproval")}
        <Switch
          checked={forced || c.requires_approval === true}
          disabled={readOnly || forced}
          onCheckedChange={(checked) => set("requires_approval", checked)}
          aria-label={t("panel.requiresApproval")}
        />
      </label>
      {forced ? <p className="text-[11px] text-fg-subtle">{t("panel.approvalForced")}</p> : null}
      {forced || c.requires_approval === true ? roleField() : null}
    </div>
  );

  const templateField = (field: string, label: string, opts: { multiline?: boolean; hint?: string; placeholder?: string; mono?: boolean } = {}) => (
    <PanelField label={label} htmlFor={fid(field)} hint={opts.hint} issues={fieldIssues(field)}>
      <TemplateField
        id={fid(field)}
        value={asText(c[field])}
        multiline={opts.multiline}
        rows={opts.multiline ? 4 : undefined}
        mono={opts.mono}
        placeholder={opts.placeholder}
        options={options}
        disabled={readOnly}
        invalid={fieldIssues(field).length > 0}
        onChange={(v) => set(field, v)}
      />
    </PanelField>
  );

  let form: React.ReactNode = null;
  switch (node.type) {
    case "input":
      form = (
        <PanelField label={t("inputs.title")}>
          <InputsEditor inputs={doc.inputs} onChange={onInputs} disabled={readOnly} />
        </PanelField>
      );
      break;
    case "agent":
      form = (
        <>
          <PanelField label={t("panel.agent")} htmlFor={fid("agent")} issues={fieldIssues("agent")}>
            {palette.agents.length ? (
              <Select
                id={fid("agent")}
                value={str(c.agent) || undefined}
                placeholder={t("panel.chooseAgent")}
                disabled={readOnly}
                onValueChange={(v) => set("agent", v)}
                options={palette.agents.map((a) => ({ value: a.name, label: a.name, description: a.description || undefined }))}
              />
            ) : (
              <Alert tone="info">
                {t("panel.noAgents")}{" "}
                <Link className="underline" href={`/app/projects/${projectId}/agents?new=1`}>
                  {t("panel.createAgent")}
                </Link>
              </Alert>
            )}
          </PanelField>
          {templateField("prompt", t("panel.prompt"), { multiline: true, hint: t("panel.agentPromptHint") })}
        </>
      );
      break;
    case "llm": {
      const tier = c.model ? "custom" : str(c.model_tier, "standard");
      form = (
        <>
          <PanelField label={t("panel.model")} htmlFor={fid("model_tier")} issues={fieldIssues("model")}>
            <Select
              id={fid("model_tier")}
              value={tier}
              disabled={readOnly}
              onValueChange={(v) =>
                v === "custom"
                  ? onConfig({ model_tier: null, model: str(c.model) || palette.model_tiers[1]?.model || "" }, "model")
                  : onConfig({ model_tier: v, model: null }, "model")
              }
              options={[
                ...palette.model_tiers.map((m) => ({ value: m.tier, label: t(`panel.tiers.${m.tier}`), description: m.model })),
                { value: "custom", label: t("panel.tiers.custom") },
              ]}
            />
            {tier === "custom" ? (
              <Input
                className="mt-1.5 font-mono text-xs"
                aria-label={t("panel.customModel")}
                value={str(c.model)}
                disabled={readOnly}
                placeholder="anthropic/…"
                onChange={(e) => set("model", e.target.value)}
              />
            ) : null}
          </PanelField>
          <PanelField label={t("panel.system")} htmlFor={fid("system")} hint={t("panel.systemHint")} issues={fieldIssues("system")}>
            <Textarea id={fid("system")} value={str(c.system)} rows={3} disabled={readOnly} onChange={(e) => set("system", e.target.value)} />
          </PanelField>
          {templateField("prompt", t("panel.prompt"), { multiline: true })}
          <label className="flex items-center justify-between gap-2 text-xs font-medium">
            {t("panel.jsonOutput")}
            <Switch checked={c.json_output === true} disabled={readOnly} onCheckedChange={(v) => set("json_output", v)} aria-label={t("panel.jsonOutput")} />
          </label>
          <div className="grid grid-cols-2 gap-2">
            <PanelField label={t("panel.maxTokens")} htmlFor={fid("max_tokens")} issues={fieldIssues("max_tokens")}>
              <Input id={fid("max_tokens")} type="number" min={16} max={64000} value={String(num(c.max_tokens, 1024))} disabled={readOnly}
                onChange={(e) => set("max_tokens", Number(e.target.value))} />
            </PanelField>
            <PanelField label={t("panel.temperature")} htmlFor={fid("temperature")} issues={fieldIssues("temperature")}>
              <Input id={fid("temperature")} type="number" min={0} max={1} step={0.1} value={c.temperature === null || c.temperature === undefined ? "" : String(c.temperature)}
                placeholder={t("panel.default")} disabled={readOnly}
                onChange={(e) => set("temperature", e.target.value === "" ? null : Number(e.target.value))} />
            </PanelField>
          </div>
        </>
      );
      break;
    }
    case "tool": {
      const tool = palette.tools.find((x) => x.key === c.tool);
      const optionsCfg = obj(c.options);
      const args = obj(c.args);
      form = (
        <>
          <PanelField label={t("panel.tool")} htmlFor={fid("tool")} issues={fieldIssues("tool")}>
            <Select
              id={fid("tool")}
              value={str(c.tool) || undefined}
              disabled={readOnly}
              onValueChange={(v) => onConfig({ tool: v, args: {}, options: {} }, "tool")}
              options={palette.tools.map((x) => ({ value: x.key, label: t.has(`tools.${x.key}`) ? t(`tools.${x.key}`) : x.label }))}
            />
          </PanelField>
          {tool?.params.map((param) => (
            <PanelField key={param} label={<code className="font-mono">{param}</code>} htmlFor={fid(`args.${param}`)} issues={fieldIssues(`args.${param}`)}>
              <TemplateField
                id={fid(`args.${param}`)}
                value={asText(args[param])}
                options={options}
                disabled={readOnly}
                multiline={param === "body" || param === "sql"}
                onChange={(v) => onConfig({ args: { ...args, [param]: v } }, `args.${param}`)}
              />
            </PanelField>
          ))}
          {c.tool === "knowledge_search" ? (
            <KbChecklist palette={palette} value={Array.isArray(optionsCfg.kb_ids) ? (optionsCfg.kb_ids as string[]) : []} disabled={readOnly}
              issues={fieldIssues("options.kb_ids")}
              onChange={(kb_ids) => onConfig({ options: { ...optionsCfg, kb_ids } }, "options")} />
          ) : null}
          {c.tool === "sql_query" ? (
            <KbSelect palette={palette} id={fid("options.kb_id")} value={str(optionsCfg.kb_id)} disabled={readOnly} issues={fieldIssues("options.kb_id")}
              onChange={(kb_id) => onConfig({ options: { ...optionsCfg, kb_id } }, "options")} />
          ) : null}
          {c.tool === "current_datetime" ? (
            <PanelField label={t("panel.timezone")} htmlFor={fid("options.timezone")}>
              <Input id={fid("options.timezone")} value={str(optionsCfg.timezone, "Europe/Madrid")} disabled={readOnly}
                onChange={(e) => onConfig({ options: { ...optionsCfg, timezone: e.target.value } }, "options")} />
            </PanelField>
          ) : null}
          {c.tool === "read_url" || c.tool === "http_request" ? (
            <AllowedHosts id={fid("options.allowed_hosts")} value={Array.isArray(optionsCfg.allowed_hosts) ? (optionsCfg.allowed_hosts as string[]) : []}
              disabled={readOnly} onChange={(allowed_hosts) => onConfig({ options: { ...optionsCfg, allowed_hosts } }, "options")} />
          ) : null}
          {approvalSwitch(c.tool === "send_email")}
        </>
      );
      break;
    }
    case "connector_action":
      form = <ConnectorForm node={node} palette={palette} options={options} readOnly={readOnly} fieldIssues={fieldIssues} onConfig={onConfig} approval={approvalSwitch()} />;
      break;
    case "knowledge_search":
      form = (
        <>
          <KbChecklist palette={palette} value={Array.isArray(c.kb_ids) ? (c.kb_ids as string[]) : []} disabled={readOnly}
            issues={fieldIssues("kb_ids")} onChange={(kb_ids) => set("kb_ids", kb_ids)} />
          {templateField("query", t("panel.query"), { multiline: true })}
          <div className="grid grid-cols-2 gap-2">
            <PanelField label={t("panel.k")} htmlFor={fid("k")}>
              <Input id={fid("k")} type="number" min={1} max={50} value={String(num(c.k, 5))} disabled={readOnly} onChange={(e) => set("k", Number(e.target.value))} />
            </PanelField>
            <PanelField label={t("panel.mode")} htmlFor={fid("mode")}>
              <Select id={fid("mode")} value={str(c.mode, "hybrid")} disabled={readOnly} onValueChange={(v) => set("mode", v)}
                options={["hybrid", "vector", "keyword"].map((m) => ({ value: m, label: t(`panel.searchModes.${m}`) }))} />
            </PanelField>
          </div>
        </>
      );
      break;
    case "sql_query": {
      const params = Array.isArray(c.params) ? (c.params as unknown[]) : [];
      form = (
        <>
          <KbSelect palette={palette} id={fid("kb_id")} value={str(c.kb_id)} disabled={readOnly} issues={fieldIssues("kb_id")} onChange={(v) => set("kb_id", v)} />
          <PanelField label={t("panel.sql")} htmlFor={fid("sql")} hint={t("panel.sqlHint")} issues={fieldIssues("sql")}>
            <Textarea id={fid("sql")} value={str(c.sql)} rows={5} className="font-mono text-xs" disabled={readOnly} onChange={(e) => set("sql", e.target.value)} />
          </PanelField>
          <PanelField label={t("panel.params")} issues={fieldIssues("params")}>
            <div className="space-y-1.5">
              {params.map((p, i) => (
                <div key={i} className="flex items-start gap-1.5">
                  <span className="mt-1.5 w-6 shrink-0 font-mono text-[11px] text-fg-subtle">${i + 1}</span>
                  <div className="min-w-0 flex-1">
                    <TemplateField value={asText(p)} options={options} disabled={readOnly}
                      onChange={(v) => set("params", params.map((x, j) => (j === i ? v : x)))} />
                  </div>
                  <Button variant="ghost" size="icon-sm" aria-label={t("panel.removeParam", { n: i + 1 })} disabled={readOnly}
                    onClick={() => set("params", params.filter((_, j) => j !== i))}>
                    <X />
                  </Button>
                </div>
              ))}
              {!readOnly ? (
                <Button size="sm" variant="secondary" onClick={() => set("params", [...params, ""])}>
                  <Plus />
                  {t("panel.addParam")}
                </Button>
              ) : null}
            </div>
          </PanelField>
        </>
      );
      break;
    }
    case "http_request": {
      const method = str(c.method, "GET");
      form = (
        <>
          <PanelField label={t("panel.method")} htmlFor={fid("method")}>
            <Select id={fid("method")} value={method} disabled={readOnly} onValueChange={(v) => set("method", v)}
              options={["GET", "POST", "PUT", "PATCH", "DELETE"].map((m) => ({ value: m, label: m }))} />
          </PanelField>
          {method !== "GET" ? <Alert tone="warning">{t("panel.httpApproval")}</Alert> : null}
          {templateField("url", t("panel.url"), { placeholder: "https://api.example.com/…", mono: true })}
          <PanelField label={t("panel.queryParams")} issues={fieldIssues("query")}>
            <KeyValueEditor idPrefix={fid("query")} value={obj(c.query)} options={options} disabled={readOnly} onChange={(v) => set("query", v)} />
          </PanelField>
          <PanelField label={t("panel.headers")} hint={t("panel.headersHint")}>
            <KeyValueEditor idPrefix={fid("headers")} value={obj(c.headers)} options={null} disabled={readOnly} suggestions={["Authorization", "Accept"]}
              onChange={(v) => set("headers", Object.fromEntries(Object.entries(v).map(([k, x]) => [k, asText(x)])))} />
          </PanelField>
          {method !== "GET" ? (
            <PanelField label={t("panel.body")} issues={fieldIssues("body")}>
              <ValueEditor id={fid("body")} value={c.body ?? ""} options={options} disabled={readOnly} onChange={(v) => set("body", v)} />
            </PanelField>
          ) : null}
          {method !== "GET" ? roleField() : null}
          <AllowedHosts id={fid("allowed_hosts")} value={Array.isArray(c.allowed_hosts) ? (c.allowed_hosts as string[]) : []} disabled={readOnly}
            onChange={(v) => set("allowed_hosts", v)} />
        </>
      );
      break;
    }
    case "condition": {
      const branches = doc.edges.filter((e) => e.source === node.id);
      form = (
        <>
          {templateField("expression", t("panel.expression"), { multiline: true, mono: true, hint: t("panel.expressionHint") })}
          <div className="rounded-md border border-border p-2.5 text-xs text-fg-muted">
            <p className="font-medium text-fg">{t("panel.branches")}</p>
            <p className="mt-1">
              {t("canvas.branchTrue")}: {branches.filter((e) => e.condition === "true").map((e) => e.target).join(", ") || "—"}
            </p>
            <p>
              {t("canvas.branchFalse")}: {branches.filter((e) => e.condition === "false").map((e) => e.target).join(", ") || "—"}
            </p>
          </div>
        </>
      );
      break;
    }
    case "loop": {
      const bodies = bodyOf(doc);
      const candidates = doc.nodes.filter(
        (n) => LOOP_BODY_TYPES.includes(n.type) && n.id !== node.id && (!bodies.has(n.id) || bodies.get(n.id) === node.id),
      );
      const mode = str(c.mode, "foreach");
      form = (
        <>
          <PanelField label={t("panel.loopMode")} htmlFor={fid("mode")}>
            <Select id={fid("mode")} value={mode} disabled={readOnly} onValueChange={(v) => set("mode", v)}
              options={[{ value: "foreach", label: t("panel.loopForeach") }, { value: "count", label: t("panel.loopCount") }]} />
          </PanelField>
          {mode === "foreach"
            ? templateField("items", t("panel.items"), { hint: t("panel.itemsHint"), mono: true })
            : (
              <PanelField label={t("panel.count")} htmlFor={fid("count")} issues={fieldIssues("count")}>
                <Input id={fid("count")} type="number" min={1} max={palette.limits.max_loop_items} value={String(num(c.count, 1))} disabled={readOnly}
                  onChange={(e) => set("count", Number(e.target.value))} />
              </PanelField>
            )}
          <PanelField label={t("panel.body")} htmlFor={fid("body")} hint={t("panel.loopBodyHint", { id: node.id })} issues={fieldIssues("body")}>
            <Select id={fid("body")} value={str(c.body) || undefined} placeholder={t("panel.chooseBody")} disabled={readOnly || candidates.length === 0}
              onValueChange={(v) => onConfig({ body: v }, "body")}
              options={candidates.map((n) => ({ value: n.id, label: n.label || n.id, description: n.id }))} />
          </PanelField>
          <PanelField label={t("panel.maxItems")} htmlFor={fid("max_items")} hint={t("panel.maxItemsHint", { max: palette.limits.max_loop_items })}>
            <Input id={fid("max_items")} type="number" min={1} max={palette.limits.max_loop_items} value={String(num(c.max_items, 100))} disabled={readOnly}
              onChange={(e) => set("max_items", Number(e.target.value))} />
          </PanelField>
        </>
      );
      break;
    }
    case "transform":
    case "output":
      form = (
        <PanelField label={node.type === "output" ? t("panel.outputValue") : t("panel.transformValue")} htmlFor={fid("value")}
          hint={node.type === "output" ? t("panel.outputHint") : t("panel.transformHint")} issues={fieldIssues("value")}>
          <ValueEditor id={fid("value")} value={c.value ?? ""} options={options} disabled={readOnly} invalid={fieldIssues("value").length > 0} onChange={(v) => set("value", v)} />
        </PanelField>
      );
      break;
    case "approval":
      form = (
        <>
          {templateField("prompt", t("panel.approvalPrompt"), { multiline: true, hint: t("panel.approvalPromptHint") })}
          <PanelField label={tc("description")} htmlFor={fid("description")}>
            <Input id={fid("description")} value={str(c.description)} disabled={readOnly} onChange={(e) => set("description", e.target.value)} />
          </PanelField>
          <PanelField label={t("panel.payload")} hint={t("panel.payloadHint")} issues={fieldIssues("payload")}>
            <KeyValueEditor idPrefix={fid("payload")} value={obj(c.payload)} options={options} disabled={readOnly} onChange={(v) => set("payload", v)} />
          </PanelField>
          {roleField()}
        </>
      );
      break;
    case "wait":
      form = (
        <PanelField label={t("panel.seconds")} htmlFor={fid("seconds")} hint={t("panel.waitHint", { max: palette.limits.max_wait_seconds })} issues={fieldIssues("seconds")}>
          <Input id={fid("seconds")} type="number" min={1} max={palette.limits.max_wait_seconds} value={String(num(c.seconds, 5))} disabled={readOnly}
            onChange={(e) => set("seconds", Number(e.target.value))} />
        </PanelField>
      );
      break;
    case "sub_workflow": {
      const choices = palette.workflows.filter((w) => w.name !== doc.name);
      form = (
        <>
          <PanelField label={t("panel.workflow")} htmlFor={fid("workflow")} issues={fieldIssues("workflow")}>
            {choices.length ? (
              <Select id={fid("workflow")} value={str(c.workflow) || undefined} placeholder={t("panel.chooseWorkflow")} disabled={readOnly}
                onValueChange={(v) => set("workflow", v)} options={choices.map((w) => ({ value: w.name, label: w.name, description: w.description || undefined }))} />
            ) : (
              <Alert tone="info">{t("panel.noWorkflows")}</Alert>
            )}
          </PanelField>
          <PanelField label={t("panel.args")} hint={t("panel.subWorkflowArgsHint")} issues={fieldIssues("args")}>
            <KeyValueEditor idPrefix={fid("args")} value={obj(c.args)} options={options} disabled={readOnly} onChange={(v) => set("args", v)} />
          </PanelField>
        </>
      );
      break;
    }
    case "custom": {
      const fn = functions.find((f) => f.name === c.function);
      form = (
        <>
          <PanelField
            label={t("panel.function")}
            htmlFor={fid("function")}
            issues={fieldIssues("function")}
            action={
              <Button variant="link" size="sm" className="h-auto text-[11px]" onClick={onOpenCustomNodes}>
                <Code2 className="!size-3" />
                {t("panel.editNodes")}
              </Button>
            }
          >
            <Select id={fid("function")} value={str(c.function) || undefined} placeholder={t("panel.chooseFunction")} disabled={readOnly || functions.length === 0}
              onValueChange={(v) => set("function", v)}
              options={functions.map((f) => ({ value: f.name, label: f.name, description: f.description || undefined }))} />
          </PanelField>
          <PanelField label={t("panel.args")} issues={fieldIssues("args")}>
            <KeyValueEditor idPrefix={fid("args")} value={obj(c.args)} options={options} disabled={readOnly} suggestions={fn?.params.map((p) => p.name) ?? []}
              onChange={(v) => set("args", v)} />
          </PanelField>
          {approvalSwitch()}
        </>
      );
      break;
    }
    default:
      form = null;
  }

  return (
    <aside className="flex w-[22rem] shrink-0 flex-col border-l border-border bg-bg" aria-label={t("panel.title")}>
      <div className="flex items-center gap-2 border-b border-border px-3 py-2.5">
        <Icon className="size-4 text-fg-muted" aria-hidden />
        <p className="min-w-0 flex-1 truncate text-sm font-semibold">{t(`nodeTypes.${node.type}.label`)}</p>
        <Button variant="ghost" size="icon-sm" aria-label={tc("close")} onClick={onClose}>
          <X />
        </Button>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        <p className="text-xs text-fg-muted">{t(`nodeTypes.${node.type}.description`)}</p>
        <FieldIssues messages={generalIssues} />
        <PanelField label={t("panel.label")} htmlFor={fid("label")}>
          <Input id={fid("label")} value={node.label} disabled={readOnly} maxLength={120} onChange={(e) => onLabel(e.target.value)} />
        </PanelField>
        <PanelField label={t("panel.id")} htmlFor={fid("id")} hint={t("panel.idHint")} issues={idError ? [idError] : []}>
          <Input
            id={fid("id")}
            value={idDraft}
            disabled={readOnly}
            className="font-mono text-xs"
            onChange={(e) => setIdDraft(e.target.value)}
            onBlur={commitId}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                commitId();
              }
            }}
          />
        </PanelField>
        {form}
      </div>
      {!readOnly && node.type !== "input" ? (
        <div className="border-t border-border p-3">
          <Button variant="danger" size="sm" onClick={() => setConfirmDelete(true)}>
            <Trash2 />
            {t("panel.deleteNode")}
          </Button>
        </div>
      ) : null}
      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title={t("panel.deleteTitle", { id: node.id })}
        description={t("panel.deleteDescription")}
        confirmLabel={tc("delete")}
        cancelLabel={tc("cancel")}
        destructive
        onConfirm={() => {
          setConfirmDelete(false);
          onDelete();
        }}
      />
    </aside>
  );
}

function KbChecklist({
  palette,
  value,
  onChange,
  disabled,
  issues,
}: {
  palette: Palette;
  value: string[];
  onChange: (value: string[]) => void;
  disabled: boolean;
  issues: string[];
}) {
  const t = useTranslations("workflows.panel");
  return (
    <PanelField label={t("knowledgeBases")} issues={issues}>
      {palette.knowledge_bases.length === 0 ? (
        <Alert tone="info">
          {t("noKnowledgeBases")}{" "}
          <Link className="underline" href="/app/knowledge">
            {t("openKnowledge")}
          </Link>
        </Alert>
      ) : (
        <ul className="space-y-1 rounded-md border border-border p-2">
          {palette.knowledge_bases.map((kb) => (
            <li key={kb.id}>
              <label className="flex items-center gap-2 text-xs">
                <Checkbox
                  checked={value.includes(kb.id)}
                  disabled={disabled}
                  onCheckedChange={(checked) => onChange(checked === true ? [...value, kb.id] : value.filter((v) => v !== kb.id))}
                />
                {kb.name}
              </label>
            </li>
          ))}
        </ul>
      )}
    </PanelField>
  );
}

function KbSelect({
  palette,
  id,
  value,
  onChange,
  disabled,
  issues,
}: {
  palette: Palette;
  id: string;
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
  issues: string[];
}) {
  const t = useTranslations("workflows.panel");
  return (
    <PanelField label={t("knowledgeBase")} htmlFor={id} issues={issues}>
      {palette.knowledge_bases.length === 0 ? (
        <Alert tone="info">{t("noKnowledgeBases")}</Alert>
      ) : (
        <Select id={id} value={value || undefined} placeholder={t("chooseKnowledgeBase")} disabled={disabled} onValueChange={onChange}
          options={palette.knowledge_bases.map((kb) => ({ value: kb.id, label: kb.name }))} />
      )}
    </PanelField>
  );
}

function AllowedHosts({ id, value, onChange, disabled }: { id: string; value: string[]; onChange: (value: string[]) => void; disabled: boolean }) {
  const t = useTranslations("workflows.panel");
  const [draft, setDraft] = React.useState(value.join(", "));
  React.useEffect(() => setDraft(value.join(", ")), [value]);
  return (
    <PanelField label={t("allowedHosts")} htmlFor={id} hint={t("allowedHostsHint")}>
      <Input
        id={id}
        value={draft}
        disabled={disabled}
        placeholder="api.example.com"
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => onChange(draft.split(",").map((h) => h.trim().toLowerCase()).filter(Boolean))}
      />
    </PanelField>
  );
}

function ConnectorForm({
  node,
  palette,
  options,
  readOnly,
  fieldIssues,
  onConfig,
  approval,
}: {
  node: WorkflowNode;
  palette: Palette;
  options: ReturnType<typeof bindingOptions>;
  readOnly: boolean;
  fieldIssues: (field: string) => string[];
  onConfig: (patch: Config, field: string) => void;
  approval: React.ReactNode;
}) {
  const t = useTranslations("workflows.panel");
  const c = node.config;
  const connectionId = str(c.connection_id) || null;
  const actions = useConnectionActions(connectionId);
  const action = actions.data?.find((a) => a.name === c.action);
  const properties = Object.keys(action?.input_schema?.properties ?? {});
  return (
    <>
      <PanelField label={t("connection")} htmlFor={`${node.id}-connection`} issues={fieldIssues("connection_id")}>
        {palette.connections.length === 0 ? (
          <Alert tone="info">
            {t("noConnections")}{" "}
            <Link className="underline" href="/app/connectors">
              {t("openConnectors")}
            </Link>
          </Alert>
        ) : (
          <Select
            id={`${node.id}-connection`}
            value={connectionId ?? undefined}
            placeholder={t("chooseConnection")}
            disabled={readOnly}
            onValueChange={(v) => onConfig({ connection_id: v, action: "", args: {} }, "connection_id")}
            options={palette.connections.map((conn) => ({
              value: conn.id,
              label: conn.name,
              description: `${conn.connector_name}${conn.demo ? ` · ${t("demo")}` : ""}`,
            }))}
          />
        )}
      </PanelField>
      {connectionId ? (
        <PanelField label={t("action")} htmlFor={`${node.id}-action`} issues={fieldIssues("action")}>
          {actions.isLoading ? (
            <p className="text-xs text-fg-subtle">{t("loadingActions")}</p>
          ) : actions.data === null || actions.error ? (
            <Input id={`${node.id}-action`} value={str(c.action)} disabled={readOnly} className="font-mono text-xs"
              onChange={(e) => onConfig({ action: e.target.value }, "action")} />
          ) : (
            <Select
              id={`${node.id}-action`}
              value={str(c.action) || undefined}
              placeholder={t("chooseAction")}
              disabled={readOnly}
              onValueChange={(v) => {
                const spec = actions.data?.find((a) => a.name === v);
                onConfig({ action: v, requires_approval: Boolean(spec?.requires_approval ?? spec?.side_effect) }, "action");
              }}
              options={(actions.data ?? []).map((a) => ({ value: a.name, label: a.title || a.name, description: a.description || undefined }))}
            />
          )}
        </PanelField>
      ) : null}
      {action?.side_effect ? <Alert tone="warning">{t("sideEffect")}</Alert> : null}
      <PanelField label={t("args")} issues={fieldIssues("args")}>
        <KeyValueEditor idPrefix={`${node.id}-args`} value={obj(c.args)} options={options} disabled={readOnly} suggestions={properties}
          onChange={(v) => onConfig({ args: v }, "args")} />
      </PanelField>
      {approval}
    </>
  );
}
