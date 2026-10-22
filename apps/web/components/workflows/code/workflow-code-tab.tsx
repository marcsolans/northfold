"use client";

import { Alert } from "@messer/ui";
import { useTranslations } from "next-intl";
import * as React from "react";

import { CodeEditor, type CodeMarker } from "@/components/studio/monaco";

export interface CodeProblem {
  message: string;
  line: number | null;
  column: number | null;
}

/** Monaco on workflow.py. In code mode the file is the source of truth and the canvas is read-only. */
export function WorkflowCodeTab({
  path,
  code,
  onChange,
  onSave,
  readOnlyReason,
  codeMode,
  problem,
}: {
  path: string;
  code: string;
  onChange: (code: string) => void;
  onSave: () => void;
  readOnlyReason: "viewer" | "graph_dirty" | null;
  codeMode: boolean;
  problem: CodeProblem | null;
}) {
  const t = useTranslations("workflows.code");
  const markers = React.useMemo<CodeMarker[]>(
    () => (problem?.line ? [{ line: problem.line, column: problem.column ?? undefined, message: problem.message }] : []),
    [problem],
  );
  return (
    <div className="flex h-full min-h-[28rem] flex-col">
      <div className="flex flex-col gap-2 px-4 py-3 md:px-5">
        {codeMode ? (
          <Alert tone="info" title={t("codeModeTitle")}>
            {t("codeModeBanner")}
          </Alert>
        ) : (
          <p className="text-xs text-fg-muted">{t("syncHint")}</p>
        )}
        {readOnlyReason === "graph_dirty" ? <Alert tone="warning">{t("graphDirty")}</Alert> : null}
        {readOnlyReason === "viewer" ? <Alert tone="info">{t("viewer")}</Alert> : null}
        {problem ? (
          <Alert tone="danger" title={t("syntaxError")}>
            {problem.message}
          </Alert>
        ) : null}
      </div>
      <div className="min-h-0 flex-1 border-y border-border">
        <CodeEditor
          path={path}
          value={code}
          onChange={onChange}
          onSave={onSave}
          readOnly={readOnlyReason !== null}
          markers={markers}
          ariaLabel={t("editorLabel", { path })}
        />
      </div>
      <p className="px-4 py-2 font-mono text-[11px] text-fg-subtle md:px-5">{path}</p>
    </div>
  );
}
