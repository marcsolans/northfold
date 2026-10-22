"use client";

import type { Monaco, OnMount } from "@monaco-editor/react";
import { Skeleton } from "@messer/ui";
import dynamic from "next/dynamic";
import { useTheme } from "next-themes";
import * as React from "react";

/** Monaco is served from our own origin (strict CSP, no CDN). */
async function loadMonacoReact() {
  const mod = await import("@monaco-editor/react");
  mod.loader.config({ paths: { vs: "/monaco/vs" } });
  return mod;
}

const Editor = dynamic(async () => (await loadMonacoReact()).Editor, {
  ssr: false,
  loading: () => <Skeleton className="h-full min-h-64 w-full rounded-none" />,
});

const DiffEditorLazy = dynamic(async () => (await loadMonacoReact()).DiffEditor, {
  ssr: false,
  loading: () => <Skeleton className="h-full min-h-64 w-full rounded-none" />,
});

function useMonacoTheme(): string {
  const { resolvedTheme } = useTheme();
  return resolvedTheme === "dark" ? "vs-dark" : "light";
}

export interface CodeMarker {
  line: number;
  column?: number;
  message: string;
}

export function CodeEditor({
  value,
  onChange,
  language = "python",
  readOnly = false,
  markers = [],
  onSave,
  ariaLabel,
  path,
}: {
  value: string;
  onChange?: (value: string) => void;
  language?: string;
  readOnly?: boolean;
  markers?: CodeMarker[];
  onSave?: () => void;
  ariaLabel: string;
  path?: string;
}) {
  const theme = useMonacoTheme();
  const editorRef = React.useRef<Parameters<OnMount>[0] | null>(null);
  const monacoRef = React.useRef<Monaco | null>(null);
  const saveRef = React.useRef(onSave);
  React.useEffect(() => {
    saveRef.current = onSave;
  }, [onSave]);

  const applyMarkers = React.useCallback(() => {
    const editor = editorRef.current;
    const monaco = monacoRef.current;
    const model = editor?.getModel();
    if (!editor || !monaco || !model) return;
    monaco.editor.setModelMarkers(
      model,
      "messer",
      markers.map((m) => ({
        severity: monaco.MarkerSeverity.Error,
        message: m.message,
        startLineNumber: m.line,
        endLineNumber: m.line,
        startColumn: m.column ?? 1,
        endColumn: model.getLineMaxColumn(Math.min(Math.max(m.line, 1), model.getLineCount())),
      })),
    );
    if (markers[0]) editor.revealLineInCenterIfOutsideViewport(markers[0].line);
  }, [markers]);

  React.useEffect(() => {
    applyMarkers();
  }, [applyMarkers]);

  return (
    <Editor
      height="100%"
      language={language}
      value={value}
      path={path}
      theme={theme}
      onChange={(v) => onChange?.(v ?? "")}
      onMount={(editor, monaco) => {
        editorRef.current = editor;
        monacoRef.current = monaco;
        editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => saveRef.current?.());
        applyMarkers();
      }}
      options={{
        readOnly,
        minimap: { enabled: false },
        fontSize: 13,
        lineNumbersMinChars: 3,
        scrollBeyondLastLine: false,
        automaticLayout: true,
        tabSize: 4,
        renderWhitespace: "selection",
        ariaLabel,
        wordWrap: "on",
      }}
    />
  );
}

export function DiffViewer({
  original,
  modified,
  language = "python",
  ariaLabel,
}: {
  original: string;
  modified: string;
  language?: string;
  ariaLabel: string;
}) {
  const theme = useMonacoTheme();
  return (
    <DiffEditorLazy
      height="100%"
      language={language}
      original={original}
      modified={modified}
      theme={theme}
      options={{
        readOnly: true,
        originalEditable: false,
        renderSideBySide: true,
        minimap: { enabled: false },
        fontSize: 12,
        automaticLayout: true,
        scrollBeyondLastLine: false,
        ariaLabel,
      }}
    />
  );
}

export function languageFor(path: string): string {
  if (path.endsWith(".py")) return "python";
  if (path.endsWith(".yaml") || path.endsWith(".yml")) return "yaml";
  if (path.endsWith(".json")) return "json";
  if (path.endsWith(".md")) return "markdown";
  return "plaintext";
}
