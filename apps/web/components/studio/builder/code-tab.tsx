"use client";

import { Alert } from "@messer/ui";
import { useTranslations } from "next-intl";
import * as React from "react";

import { CodeEditor, type CodeMarker } from "../monaco";

export interface CodeError {
  message: string;
  line: number | null;
  column: number | null;
}

export function CodeTab({
  path,
  code,
  onChange,
  onSave,
  readOnlyReason,
  sourceMode,
  error,
}: {
  path: string;
  code: string;
  onChange: (code: string) => void;
  onSave: () => void;
  readOnlyReason: "viewer" | "config_dirty" | null;
  sourceMode: "config" | "code";
  error: CodeError | null;
}) {
  const t = useTranslations("studio.builder.code");
  const markers = React.useMemo<CodeMarker[]>(
    () => (error?.line ? [{ line: error.line, column: error.column ?? undefined, message: error.message }] : []),
    [error],
  );
  return (
    <div className="flex h-full min-h-[28rem] flex-col">
      <div className="flex flex-col gap-2 px-4 py-3 md:px-5">
        {sourceMode === "code" ? (
          <Alert tone="info" title={t("codeModeTitle")}>
            {t("codeModeBanner")}
          </Alert>
        ) : (
          <p className="text-xs text-fg-muted">{t("syncHint")}</p>
        )}
        {readOnlyReason === "config_dirty" ? <Alert tone="warning">{t("configDirtyBanner")}</Alert> : null}
        {readOnlyReason === "viewer" ? <Alert tone="info">{t("viewerBanner")}</Alert> : null}
        {error ? (
          <Alert tone="danger" title={t("syntaxError")}>
            {error.message}
          </Alert>
        ) : null}
      </div>
      <div className="min-h-0 flex-1 border-y border-border" aria-label={t("editorLabel", { path })}>
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
