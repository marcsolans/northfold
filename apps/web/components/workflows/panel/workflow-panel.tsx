"use client";

import { Alert, Textarea } from "@messer/ui";
import { AlertTriangle, CheckCircle2, Settings2 } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import type { WorkflowConfig, WorkflowInput } from "@/lib/workflows/types";

import { InputsEditor } from "./inputs-editor";
import { PanelField } from "./fields";

export interface ListedIssue {
  key: string;
  message: string;
  nodeId?: string;
}

/** Shown when no node is selected: description, inputs and every problem of the graph. */
export function WorkflowPanel({
  doc,
  issues,
  readOnly,
  onDescription,
  onInputs,
  onSelectNode,
}: {
  doc: WorkflowConfig;
  issues: ListedIssue[];
  readOnly: boolean;
  onDescription: (value: string) => void;
  onInputs: (inputs: WorkflowInput[]) => void;
  onSelectNode: (id: string) => void;
}) {
  const t = useTranslations("workflows");
  const tc = useTranslations("common");
  return (
    <aside className="flex w-[22rem] shrink-0 flex-col border-l border-border bg-bg" aria-label={t("panel.workflowTitle")}>
      <div className="flex items-center gap-2 border-b border-border px-3 py-2.5">
        <Settings2 className="size-4 text-fg-muted" aria-hidden />
        <p className="text-sm font-semibold">{t("panel.workflowTitle")}</p>
      </div>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-3">
        <p className="text-xs text-fg-muted">{t("panel.selectHint")}</p>
        <section aria-label={t("canvas.issues.title")}>
          {issues.length === 0 ? (
            <p className="flex items-center gap-1.5 text-xs text-success">
              <CheckCircle2 className="size-3.5" aria-hidden />
              {t("canvas.issues.none")}
            </p>
          ) : (
            <Alert tone="danger" title={t("canvas.issues.count", { n: issues.length })}>
              <ul className="mt-1 space-y-1">
                {issues.map((issue) => (
                  <li key={issue.key}>
                    {issue.nodeId ? (
                      <button type="button" className="text-left underline-offset-2 hover:underline" onClick={() => onSelectNode(issue.nodeId as string)}>
                        <code className="font-mono">{issue.nodeId}</code>: {issue.message}
                      </button>
                    ) : (
                      <span className="flex items-start gap-1">
                        <AlertTriangle className="mt-0.5 size-3 shrink-0" aria-hidden />
                        {issue.message}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </Alert>
          )}
        </section>
        <PanelField label={tc("description")} htmlFor="workflow-description">
          <Textarea id="workflow-description" rows={3} value={doc.description} maxLength={2000} disabled={readOnly}
            onChange={(e) => onDescription(e.target.value)} />
        </PanelField>
        <PanelField label={t("inputs.title")}>
          <InputsEditor inputs={doc.inputs} onChange={onInputs} disabled={readOnly} />
        </PanelField>
      </div>
    </aside>
  );
}
