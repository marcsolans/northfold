"use client";

import { Alert, Button, Card, CardBody, CardHeader, Field, Select, Switch, Textarea } from "@messer/ui";
import { Plus, Wrench, MessagesSquare } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { CodeEditor } from "@/components/studio/monaco";

import { IssueList } from "./issues";
import { PolicyCard } from "./policy-card";
import { issuesAt, move, newToolPolicy, newTurnPolicy, normalizePlaybook, serialize } from "./playbook-draft";
import type { GuardDetail, Issue, Playbook } from "./types";

export type EditorMode = "form" | "json";

function relative(issues: Issue[], prefix: string): Issue[] {
  return issuesAt(issues, prefix).map((i) => ({
    ...i,
    path: i.path === prefix ? "" : i.path.slice(prefix.length + 1),
  }));
}

function SchemaEditor({
  value,
  onChange,
  readOnly,
  issues,
}: {
  value: Record<string, unknown> | null;
  onChange: (value: Record<string, unknown> | null) => void;
  readOnly: boolean;
  issues: Issue[];
}) {
  const t = useTranslations("guard.editor.schema");
  const [text, setText] = React.useState(() => (value ? JSON.stringify(value, null, 2) : ""));
  const [error, setError] = React.useState<string | null>(null);
  const [seen, setSeen] = React.useState(value);
  if (JSON.stringify(seen) !== JSON.stringify(value)) {
    setSeen(value);
    setText(value ? JSON.stringify(value, null, 2) : "");
    setError(null);
  }
  const enabled = value !== null || text.trim() !== "";
  return (
    <Card>
      <CardHeader
        title={t("title")}
        description={t("description")}
        actions={
          <label className="flex items-center gap-2 text-xs text-fg-muted">
            <Switch
              checked={enabled}
              disabled={readOnly}
              aria-label={t("enable")}
              onCheckedChange={(on) => {
                const next = on ? { type: "object", properties: {}, required: [] } : null;
                setSeen(next);
                setText(next ? JSON.stringify(next, null, 2) : "");
                setError(null);
                onChange(next);
              }}
            />
            <span className="hidden sm:inline">{t("enable")}</span>
          </label>
        }
      />
      {enabled ? (
        <CardBody>
          <Field
            label={t("label")}
            htmlFor="guard-output-schema"
            error={error ? t("invalid", { error }) : undefined}
          >
            <Textarea
              id="guard-output-schema"
              value={text}
              rows={8}
              spellCheck={false}
              className="font-mono text-xs"
              disabled={readOnly}
              onChange={(e) => {
                const next = e.target.value;
                setText(next);
                try {
                  const parsed: unknown = JSON.parse(next);
                  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("{}");
                  setError(null);
                  setSeen(parsed as Record<string, unknown>);
                  onChange(parsed as Record<string, unknown>);
                } catch (err) {
                  setError(err instanceof Error ? err.message : String(err));
                }
              }}
            />
          </Field>
          <IssueList issues={issues} className="mt-2" />
        </CardBody>
      ) : null}
    </Card>
  );
}

function JsonEditor({
  detail,
  draft,
  onChange,
  onParseError,
  readOnly,
}: {
  detail: GuardDetail;
  draft: Playbook;
  onChange: (playbook: Playbook) => void;
  onParseError: (error: string | null) => void;
  readOnly: boolean;
}) {
  const t = useTranslations("guard.editor");
  const [text, setText] = React.useState(() => JSON.stringify(serialize(draft), null, 2));
  const [error, setError] = React.useState<string | null>(null);
  return (
    <div className="flex flex-col gap-2">
      {error ? <Alert tone="danger">{t("jsonInvalid", { error })}</Alert> : null}
      <div className="h-[32rem] overflow-hidden rounded-md border border-border">
        <CodeEditor
          value={text}
          language="json"
          readOnly={readOnly}
          ariaLabel={t("jsonLabel")}
          path={`guard-${detail.member}.json`}
          onChange={(next) => {
            setText(next);
            try {
              const parsed: unknown = JSON.parse(next);
              if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("{ … }");
              setError(null);
              onParseError(null);
              onChange(normalizePlaybook({ ...detail, playbook: parsed as Partial<Playbook> }));
            } catch (err) {
              const message = err instanceof Error ? err.message : String(err);
              setError(message);
              onParseError(message);
            }
          }}
        />
      </div>
    </div>
  );
}

export function PlaybookEditor({
  detail,
  draft,
  issues,
  mode,
  readOnly,
  onChange,
  onParseError,
  openPolicies,
}: {
  detail: GuardDetail;
  draft: Playbook;
  issues: Issue[];
  mode: EditorMode;
  readOnly: boolean;
  onChange: (playbook: Playbook) => void;
  onParseError: (error: string | null) => void;
  /** Policy ids to show expanded (e.g. the ones just added). */
  openPolicies: Set<string>;
}) {
  const t = useTranslations("guard.editor");
  const [added, setAdded] = React.useState<Set<string>>(new Set());

  if (mode === "json") {
    return <JsonEditor detail={detail} draft={draft} onChange={onChange} onParseError={onParseError} readOnly={readOnly} />;
  }

  const models = Array.from(
    new Map(
      [...detail.models, { id: draft.small_model, label: draft.small_model }, { id: draft.large_model, label: draft.large_model }].map(
        (m) => [m.id, m],
      ),
    ).values(),
  );
  const ids = draft.policies.map((p) => p.id);
  const setPolicies = (policies: Playbook["policies"]) => onChange({ ...draft, policies });
  const add = (kind: "turn" | "tool") => {
    const policy = kind === "turn" ? newTurnPolicy(ids) : newToolPolicy(ids, detail.tools[0]?.name);
    setAdded((prev) => new Set(prev).add(policy.id));
    setPolicies([...draft.policies, policy]);
  };
  const topLevel = issues.filter((i) => !i.path.startsWith("policies.") && !i.path.startsWith("output_schema"));

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader title={t("models.title")} />
        <CardBody className="grid gap-4 sm:grid-cols-2">
          <Field label={t("models.small")} htmlFor="guard-small-model" hint={t("models.smallHint")}>
            <Select
              id="guard-small-model"
              value={draft.small_model}
              onValueChange={(small_model) => onChange({ ...draft, small_model })}
              options={models.map((m) => ({ value: m.id, label: m.label, description: m.id }))}
              disabled={readOnly}
            />
          </Field>
          <Field label={t("models.large")} htmlFor="guard-large-model" hint={t("models.largeHint")}>
            <Select
              id="guard-large-model"
              value={draft.large_model}
              onValueChange={(large_model) => onChange({ ...draft, large_model })}
              options={models.map((m) => ({ value: m.id, label: m.label, description: m.id }))}
              disabled={readOnly}
            />
          </Field>
          {topLevel.length ? <IssueList issues={topLevel} className="sm:col-span-2" /> : null}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title={t("policies.title")}
          description={t("policies.description")}
          actions={
            !readOnly ? (
              <div className="flex flex-wrap gap-2">
                <Button size="sm" onClick={() => add("turn")}>
                  <MessagesSquare />
                  <Plus className="-ml-1 size-3" aria-hidden />
                  {t("policies.addTurn")}
                </Button>
                <Button size="sm" onClick={() => add("tool")}>
                  <Wrench />
                  <Plus className="-ml-1 size-3" aria-hidden />
                  {t("policies.addTool")}
                </Button>
              </div>
            ) : null
          }
        />
        <CardBody>
          {draft.policies.length === 0 ? (
            <p className="text-sm text-fg-muted">{t("policies.empty")}</p>
          ) : (
            <ol className="flex flex-col gap-2">
              {draft.policies.map((policy, i) => (
                <PolicyCard
                  key={`${i}-${policy.tool_action ? "tool" : "turn"}`}
                  policy={policy}
                  index={i}
                  total={draft.policies.length}
                  tools={detail.tools}
                  issues={relative(issues, `policies.${i}`)}
                  readOnly={readOnly}
                  defaultOpen={added.has(policy.id) || openPolicies.has(policy.id)}
                  onChange={(next) => setPolicies(draft.policies.map((p, j) => (j === i ? next : p)))}
                  onMove={(direction) => setPolicies(move(draft.policies, i, i + direction))}
                  onRemove={() => setPolicies(draft.policies.filter((_, j) => j !== i))}
                />
              ))}
            </ol>
          )}
        </CardBody>
      </Card>

      <SchemaEditor
        value={draft.output_schema}
        onChange={(output_schema) => onChange({ ...draft, output_schema })}
        readOnly={readOnly}
        issues={issuesAt(issues, "output_schema")}
      />
    </div>
  );
}
