"use client";

import {
  Alert,
  Badge,
  Button,
  ConfirmDialog,
  Field,
  Input,
  Select,
  Switch,
  Textarea,
  cn,
} from "@messer/ui";
import { ArrowDown, ArrowUp, ChevronRight, Plus, Trash2, X } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { useIssueText } from "./issues";
import { issuesAt, listText, parseList, parseValue, valueText } from "./playbook-draft";
import type { ArgConstraint, GuardTool, Issue, Operator, Policy, ToolAction, TurnMatch } from "./types";
import { CONFIRMATIONS, LAST_MESSAGES, OPERATORS, TOOL_ACTIONS } from "./types";
import { useTextModel } from "./use-text-model";

const OTHER_TOOL = "__other__";

function lines(values: string[]): string {
  return values.join("\n");
}

function parseLines(text: string): string[] {
  return text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
}

function ListInput({
  id,
  value,
  onChange,
  disabled,
  placeholder,
}: {
  id: string;
  value: string[];
  onChange: (value: string[]) => void;
  disabled?: boolean;
  placeholder?: string;
}) {
  const [text, setText] = useTextModel(value, listText, parseList, onChange);
  return (
    <Input
      id={id}
      value={text}
      onChange={(e) => setText(e.target.value)}
      disabled={disabled}
      placeholder={placeholder}
      className="font-mono text-xs"
    />
  );
}

function LinesInput({
  id,
  value,
  onChange,
  disabled,
}: {
  id: string;
  value: string[];
  onChange: (value: string[]) => void;
  disabled?: boolean;
}) {
  const [text, setText] = useTextModel(value, lines, parseLines, onChange);
  return (
    <Textarea
      id={id}
      value={text}
      onChange={(e) => setText(e.target.value)}
      disabled={disabled}
      rows={Math.min(6, Math.max(2, value.length + 1))}
      className="font-mono text-xs"
      spellCheck={false}
    />
  );
}

function NumberInput({
  id,
  value,
  onChange,
  disabled,
}: {
  id: string;
  value: number | null;
  onChange: (value: number | null) => void;
  disabled?: boolean;
}) {
  return (
    <Input
      id={id}
      type="number"
      min={0}
      inputMode="numeric"
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value === "" ? null : Math.max(0, Math.floor(Number(e.target.value))))}
      disabled={disabled}
      className="tabular"
    />
  );
}

function errorsText(issues: Issue[], text: (i: Issue) => string): string | undefined {
  const errors = issues.filter((i) => i.level === "error");
  return errors.length ? errors.map(text).join(" ") : undefined;
}

function toolArgs(tool: GuardTool | undefined): string[] {
  const props = (tool?.input_schema as { properties?: Record<string, unknown> } | null | undefined)?.properties;
  return props && typeof props === "object" ? Object.keys(props) : [];
}

function ConstraintRow({
  idPrefix,
  constraint,
  args,
  issues,
  disabled,
  onChange,
  onRemove,
}: {
  idPrefix: string;
  constraint: ArgConstraint;
  args: string[];
  issues: Issue[];
  disabled: boolean;
  onChange: (c: ArgConstraint) => void;
  onRemove: () => void;
}) {
  const t = useTranslations("guard.editor.policy");
  const text = useIssueText();
  const format = React.useCallback((v: unknown) => valueText(v), []);
  const parse = React.useCallback((s: string) => parseValue(constraint.op, s), [constraint.op]);
  const [valueInput, setValueInput] = useTextModel<unknown>(constraint.value, format, parse, (value) =>
    onChange({ ...constraint, value }),
  );
  const needsValue = constraint.op !== "exists" && constraint.op !== "missing";
  const argOptions = Array.from(new Set([...args, ...(constraint.arg ? [constraint.arg] : [])]));
  return (
    <div className="grid grid-cols-1 gap-2 rounded-md border border-border bg-subtle/60 p-2 sm:grid-cols-[1fr_1fr_1fr_auto] sm:items-start">
      <Field label={t("arg")} htmlFor={`${idPrefix}-arg`} error={errorsText(issuesAt(issues, "arg"), text)}>
        {argOptions.length > 0 && args.length > 0 ? (
          <Select
            id={`${idPrefix}-arg`}
            value={constraint.arg || undefined}
            onValueChange={(arg) => onChange({ ...constraint, arg })}
            options={argOptions.map((a) => ({ value: a, label: a }))}
            disabled={disabled}
            placeholder={t("arg")}
          />
        ) : (
          <Input
            id={`${idPrefix}-arg`}
            value={constraint.arg}
            onChange={(e) => onChange({ ...constraint, arg: e.target.value })}
            disabled={disabled}
            className="font-mono text-xs"
          />
        )}
      </Field>
      <Field label={t("op")} htmlFor={`${idPrefix}-op`} error={errorsText(issuesAt(issues, "op"), text)}>
        <Select
          id={`${idPrefix}-op`}
          value={constraint.op}
          onValueChange={(op) => {
            const nextOp = op as Operator;
            onChange({ ...constraint, op: nextOp, value: parseValue(nextOp, valueText(constraint.value)) });
          }}
          options={OPERATORS.map((op) => ({ value: op, label: `${op} · ${t(`ops.${op}`)}` }))}
          disabled={disabled}
        />
      </Field>
      <Field
        label={constraint.op === "in" || constraint.op === "not_in" ? t("valueList") : t("value")}
        htmlFor={`${idPrefix}-value`}
        error={errorsText([...issuesAt(issues, "value"), ...issues.filter((i) => i.path === "")], text)}
      >
        <Input
          id={`${idPrefix}-value`}
          value={needsValue ? valueInput : ""}
          onChange={(e) => setValueInput(e.target.value)}
          disabled={disabled || !needsValue}
          className="font-mono text-xs"
        />
      </Field>
      {!disabled ? (
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          className="sm:mt-6"
          aria-label={t("removeConstraint")}
          onClick={onRemove}
        >
          <X />
        </Button>
      ) : null}
    </div>
  );
}

function ToolActionEditor({
  idPrefix,
  action,
  tools,
  issues,
  disabled,
  onChange,
}: {
  idPrefix: string;
  action: ToolAction;
  tools: GuardTool[];
  issues: Issue[];
  disabled: boolean;
  onChange: (action: ToolAction) => void;
}) {
  const t = useTranslations("guard.editor.policy");
  const text = useIssueText();
  const known = tools.find((tool) => tool.name === action.tool);
  const [other, setOther] = React.useState(!known && action.tool !== "");
  const selectValue = other || (!known && action.tool !== "") ? OTHER_TOOL : action.tool || undefined;
  const args = toolArgs(known);
  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("tool")} htmlFor={`${idPrefix}-tool`} error={errorsText(issuesAt(issues, "tool"), text)}>
          <Select
            id={`${idPrefix}-tool`}
            value={selectValue}
            onValueChange={(value) => {
              if (value === OTHER_TOOL) {
                setOther(true);
                return;
              }
              setOther(false);
              onChange({ ...action, tool: value });
            }}
            options={[
              ...tools.map((tool) => ({ value: tool.name, label: tool.name, description: tool.label })),
              { value: OTHER_TOOL, label: t("otherTool") },
            ]}
            disabled={disabled}
            placeholder={t("tool")}
          />
        </Field>
        <Field label={t("action")} htmlFor={`${idPrefix}-action`} error={errorsText(issuesAt(issues, "action"), text)}>
          <Select
            id={`${idPrefix}-action`}
            value={action.action}
            onValueChange={(value) => onChange({ ...action, action: value as ToolAction["action"] })}
            options={TOOL_ACTIONS.map((a) => ({ value: a, label: t(`actions.${a}`) }))}
            disabled={disabled}
          />
        </Field>
      </div>
      {selectValue === OTHER_TOOL ? (
        <Field label={t("toolPattern")} htmlFor={`${idPrefix}-pattern`}>
          <Input
            id={`${idPrefix}-pattern`}
            value={action.tool}
            onChange={(e) => onChange({ ...action, tool: e.target.value })}
            disabled={disabled}
            className="font-mono text-xs"
            placeholder="crm_*"
          />
        </Field>
      ) : null}
      {action.action === "require_approval" && known ? (
        <Alert tone={known.gated ? "info" : "warning"}>
          {known.gated ? t("gated", { tool: known.name }) : t("ungated", { tool: known.name })}
        </Alert>
      ) : null}
      <div className="flex flex-col gap-2">
        <p className="text-xs font-medium text-fg-muted">{t(`constraints.${action.action}`)}</p>
        {action.constraints.length === 0 ? <p className="text-xs text-fg-subtle">{t("constraintsAlways")}</p> : null}
        {action.constraints.map((c, k) => (
          <ConstraintRow
            key={k}
            idPrefix={`${idPrefix}-c${k}`}
            constraint={c}
            args={args}
            issues={issuesAt(issues, `constraints.${k}`).map((i) => ({
              ...i,
              path: i.path.slice(`constraints.${k}`.length + 1),
            }))}
            disabled={disabled}
            onChange={(next) =>
              onChange({ ...action, constraints: action.constraints.map((old, j) => (j === k ? next : old)) })
            }
            onRemove={() => onChange({ ...action, constraints: action.constraints.filter((_, j) => j !== k) })}
          />
        ))}
        {!disabled ? (
          <div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() =>
                onChange({
                  ...action,
                  constraints: [...action.constraints, { arg: args[0] ?? "", op: ">", value: null }],
                })
              }
            >
              <Plus />
              {t("addConstraint")}
            </Button>
          </div>
        ) : null}
      </div>
      <Field label={t("message")} htmlFor={`${idPrefix}-message`} hint={t("messageHint")}>
        <Input
          id={`${idPrefix}-message`}
          value={action.message ?? ""}
          onChange={(e) => onChange({ ...action, message: e.target.value || null })}
          disabled={disabled}
        />
      </Field>
    </div>
  );
}

function MatchEditor({
  idPrefix,
  match,
  issues,
  disabled,
  onChange,
}: {
  idPrefix: string;
  match: TurnMatch;
  issues: Issue[];
  disabled: boolean;
  onChange: (match: TurnMatch) => void;
}) {
  const t = useTranslations("guard.editor.policy");
  const text = useIssueText();
  const firstTurn = match.first_turn === null ? "any" : match.first_turn ? "yes" : "no";
  return (
    <fieldset className="flex flex-col gap-3 rounded-md border border-border p-3">
      <legend className="px-1 text-xs font-medium text-fg-muted">{t("match")}</legend>
      <p className="-mt-1 text-xs text-fg-subtle">{t("matchHint")}</p>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Field label={t("lastMessage")} htmlFor={`${idPrefix}-last`}>
          <Select
            id={`${idPrefix}-last`}
            value={match.last_message}
            onValueChange={(v) => onChange({ ...match, last_message: v as TurnMatch["last_message"] })}
            options={LAST_MESSAGES.map((m) => ({ value: m, label: t(`lastMessages.${m}`) }))}
            disabled={disabled}
          />
        </Field>
        <Field label={t("firstTurn")} htmlFor={`${idPrefix}-first`}>
          <Select
            id={`${idPrefix}-first`}
            value={firstTurn}
            onValueChange={(v) => onChange({ ...match, first_turn: v === "any" ? null : v === "yes" })}
            options={(["any", "yes", "no"] as const).map((o) => ({ value: o, label: t(`firstTurnOptions.${o}`) }))}
            disabled={disabled}
          />
        </Field>
        <Field label={t("minChars")} htmlFor={`${idPrefix}-min`}>
          <NumberInput
            id={`${idPrefix}-min`}
            value={match.min_chars}
            onChange={(v) => onChange({ ...match, min_chars: v })}
            disabled={disabled}
          />
        </Field>
        <Field label={t("maxChars")} htmlFor={`${idPrefix}-max`}>
          <NumberInput
            id={`${idPrefix}-max`}
            value={match.max_chars}
            onChange={(v) => onChange({ ...match, max_chars: v })}
            disabled={disabled}
          />
        </Field>
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <Field
          label={t("textPatterns")}
          htmlFor={`${idPrefix}-patterns`}
          hint={t("patternsHint")}
          error={errorsText(issuesAt(issues, "text_patterns"), text)}
        >
          <LinesInput
            id={`${idPrefix}-patterns`}
            value={match.text_patterns}
            onChange={(v) => onChange({ ...match, text_patterns: v })}
            disabled={disabled}
          />
        </Field>
        <Field
          label={t("textExcludes")}
          htmlFor={`${idPrefix}-excludes`}
          hint={t("patternsHint")}
          error={errorsText(issuesAt(issues, "text_excludes"), text)}
        >
          <LinesInput
            id={`${idPrefix}-excludes`}
            value={match.text_excludes}
            onChange={(v) => onChange({ ...match, text_excludes: v })}
            disabled={disabled}
          />
        </Field>
      </div>
      <Field label={t("toolResults")} htmlFor={`${idPrefix}-results`} hint={t("toolResultsHint")}>
        <ListInput
          id={`${idPrefix}-results`}
          value={match.tool_results}
          onChange={(v) => onChange({ ...match, tool_results: v })}
          disabled={disabled}
        />
      </Field>
    </fieldset>
  );
}

export function PolicyCard({
  policy,
  index,
  total,
  tools,
  issues,
  readOnly,
  defaultOpen,
  onChange,
  onMove,
  onRemove,
}: {
  policy: Policy;
  index: number;
  total: number;
  tools: GuardTool[];
  /** Issues of this policy, with paths relative to it (``tool_action.tool``…). */
  issues: Issue[];
  readOnly: boolean;
  defaultOpen: boolean;
  onChange: (policy: Policy) => void;
  onMove: (direction: -1 | 1) => void;
  onRemove: () => void;
}) {
  const t = useTranslations("guard.editor.policies");
  const tp = useTranslations("guard.editor.policy");
  const tc = useTranslations("common");
  const text = useIssueText();
  const [open, setOpen] = React.useState(defaultOpen);
  const [confirmRemove, setConfirmRemove] = React.useState(false);
  const idPrefix = `policy-${index}`;
  const isTool = policy.tool_action !== null;
  const errors = issues.filter((i) => i.level === "error").length;
  const warnings = issues.length - errors;
  const set = (patch: Partial<Policy>) => onChange({ ...policy, ...patch });
  const summary = policy.tool_action
    ? t("summaryTool", { action: tp(`actions.${policy.tool_action.action}`), tool: policy.tool_action.tool || "—" })
    : policy.response
      ? t("summaryAnswer")
      : policy.model
        ? t("summaryRoute", { model: tp(`routes.${policy.model}`).toLowerCase() })
        : "";

  return (
    <li className={cn("rounded-md border bg-surface", errors ? "border-danger/40" : "border-border")}>
      <div className="flex flex-wrap items-center gap-2 px-3 py-2">
        <button
          type="button"
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
          aria-expanded={open}
          aria-controls={`${idPrefix}-body`}
          aria-label={t("expand", { id: policy.id || "—" })}
          onClick={() => setOpen((o) => !o)}
        >
          <ChevronRight className={cn("size-4 shrink-0 text-fg-subtle transition-transform", open && "rotate-90")} />
          <span className="tabular w-5 shrink-0 text-xs text-fg-subtle">{index + 1}</span>
          <Badge tone={isTool ? "info" : "neutral"}>{isTool ? t("tool") : t("turn")}</Badge>
          <span className="truncate font-mono text-sm font-medium">{policy.id || "—"}</span>
          <span className="hidden truncate text-xs text-fg-muted md:inline">{summary}</span>
        </button>
        <Badge tone={policy.condition ? "accent" : "outline"}>
          {policy.condition ? t("semantic") : t("deterministic")}
        </Badge>
        {errors ? <Badge tone="danger">{errors}</Badge> : null}
        {warnings ? <Badge tone="warning">{warnings}</Badge> : null}
        <label className="flex items-center gap-1.5 text-xs text-fg-muted">
          <Switch
            checked={policy.enabled}
            onCheckedChange={(enabled) => set({ enabled })}
            disabled={readOnly}
            aria-label={t("enabled")}
          />
          <span className="hidden sm:inline">{t("enabled")}</span>
        </label>
        {!readOnly ? (
          <div className="flex items-center">
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={t("moveUp")}
              disabled={index === 0}
              onClick={() => onMove(-1)}
            >
              <ArrowUp />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={t("moveDown")}
              disabled={index === total - 1}
              onClick={() => onMove(1)}
            >
              <ArrowDown />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={t("remove")}
              onClick={() => setConfirmRemove(true)}
            >
              <Trash2 />
            </Button>
          </div>
        ) : null}
      </div>

      {open ? (
        <div id={`${idPrefix}-body`} className="flex flex-col gap-4 border-t border-border px-3 py-3">
          <div className="grid gap-3 sm:grid-cols-[minmax(0,14rem)_1fr]">
            <Field
              label={tp("id")}
              htmlFor={`${idPrefix}-id`}
              hint={tp("idHint")}
              error={errorsText(issuesAt(issues, "id"), text)}
            >
              <Input
                id={`${idPrefix}-id`}
                value={policy.id}
                onChange={(e) => set({ id: e.target.value })}
                disabled={readOnly}
                className="font-mono text-xs"
              />
            </Field>
            <Field label={tp("description")} htmlFor={`${idPrefix}-description`}>
              <Input
                id={`${idPrefix}-description`}
                value={policy.description}
                onChange={(e) => set({ description: e.target.value })}
                disabled={readOnly}
              />
            </Field>
          </div>

          {policy.tool_action ? (
            <ToolActionEditor
              idPrefix={idPrefix}
              action={policy.tool_action}
              tools={tools}
              issues={issuesAt(issues, "tool_action").map((i) => ({ ...i, path: i.path.slice("tool_action.".length) }))}
              disabled={readOnly}
              onChange={(tool_action) => set({ tool_action })}
            />
          ) : null}

          <MatchEditor
            idPrefix={idPrefix}
            match={policy.match}
            issues={issuesAt(issues, "match").map((i) => ({ ...i, path: i.path.slice("match.".length) }))}
            disabled={readOnly}
            onChange={(match) => set({ match })}
          />

          <div className="grid gap-3 lg:grid-cols-[1fr_minmax(0,14rem)]">
            <Field
              label={tp("condition")}
              htmlFor={`${idPrefix}-condition`}
              hint={tp("conditionHint")}
              error={errorsText(issuesAt(issues, "condition"), text)}
            >
              <Textarea
                id={`${idPrefix}-condition`}
                value={policy.condition ?? ""}
                onChange={(e) => set({ condition: e.target.value || null })}
                disabled={readOnly}
                rows={2}
              />
            </Field>
            <Field label={tp("confirmation")} htmlFor={`${idPrefix}-confirmation`}>
              <Select
                id={`${idPrefix}-confirmation`}
                value={policy.confirmation}
                onValueChange={(v) => set({ confirmation: v as Policy["confirmation"] })}
                options={CONFIRMATIONS.map((c) => ({ value: c, label: tp(`confirmations.${c}`) }))}
                disabled={readOnly || !policy.condition}
              />
            </Field>
          </div>

          {!policy.tool_action ? (
            <div className="grid gap-3 lg:grid-cols-[minmax(0,14rem)_1fr]">
              <Field label={tp("route")} htmlFor={`${idPrefix}-route`}>
                <Select
                  id={`${idPrefix}-route`}
                  value={policy.model ?? "keep"}
                  onValueChange={(v) => set({ model: v === "keep" ? null : (v as Policy["model"]) })}
                  options={(["keep", "small", "large"] as const).map((r) => ({ value: r, label: tp(`routes.${r}`) }))}
                  disabled={readOnly || Boolean(policy.response)}
                />
              </Field>
              <Field
                label={tp("response")}
                htmlFor={`${idPrefix}-response`}
                hint={tp("responseHint")}
                error={errorsText(issues.filter((i) => i.path === "" || i.path === "response"), text)}
              >
                <Textarea
                  id={`${idPrefix}-response`}
                  value={policy.response ?? ""}
                  onChange={(e) => set({ response: e.target.value || null })}
                  disabled={readOnly}
                  rows={2}
                />
              </Field>
            </div>
          ) : null}

          <div className="grid gap-3 lg:grid-cols-2">
            <Field
              label={tp("requires")}
              htmlFor={`${idPrefix}-requires`}
              hint={tp("factsHint")}
              error={errorsText([...issuesAt(issues, "requires"), ...issuesAt(issues, "facts")], text)}
            >
              <ListInput
                id={`${idPrefix}-requires`}
                value={policy.requires}
                onChange={(requires) => set({ requires })}
                disabled={readOnly}
                placeholder="approval:create_credit_note"
              />
            </Field>
            <Field label={tp("provides")} htmlFor={`${idPrefix}-provides`}>
              <ListInput
                id={`${idPrefix}-provides`}
                value={policy.provides}
                onChange={(provides) => set({ provides })}
                disabled={readOnly}
              />
            </Field>
          </div>
          {issues.some((i) => i.level === "warning") ? (
            <ul className="flex flex-col gap-1">
              {issues
                .filter((i) => i.level === "warning")
                .map((i, k) => (
                  <li key={k} className="text-xs text-warning">
                    {text(i)}
                  </li>
                ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      <ConfirmDialog
        open={confirmRemove}
        onOpenChange={setConfirmRemove}
        title={t("removeTitle", { id: policy.id || "—" })}
        description={t("removeDescription")}
        confirmLabel={t("remove")}
        cancelLabel={tc("cancel")}
        onConfirm={() => {
          setConfirmRemove(false);
          onRemove();
        }}
      />
    </li>
  );
}
