"use client";

import Editor, { type Monaco, type OnMount, loader } from "@monaco-editor/react";
import { Spinner } from "@messer/ui";
import type { Position, editor } from "monaco-editor";
import { useTheme } from "next-themes";
import * as React from "react";

import type { KbSchema } from "./types";

// Monaco is served from our own origin (strict CSP, no CDN): see scripts/copy-monaco.mjs.
loader.config({ paths: { vs: "/monaco/vs" } });

const KEYWORDS = [
  "SELECT", "FROM", "WHERE", "JOIN", "LEFT JOIN", "INNER JOIN", "ON", "GROUP BY", "ORDER BY", "HAVING", "LIMIT",
  "OFFSET", "WITH", "AS", "AND", "OR", "NOT", "IN", "IS NULL", "IS NOT NULL", "ILIKE", "LIKE", "DISTINCT", "COUNT",
  "SUM", "AVG", "MIN", "MAX", "COALESCE", "CASE", "WHEN", "THEN", "ELSE", "END", "UNION ALL", "EXPLAIN",
];

// Monaco snippet syntax: ${1:x} is a tab stop, \$1 is a literal SQL parameter.
const FUNCTION_SNIPPETS: Record<string, string> = {
  kb_vector_search: "kb_vector_search(\\$1::uuid, embed('${1:texto}'), 10)",
  kb_text_search: "kb_text_search(\\$1::uuid, '${1:texto}', 10)",
  kb_hybrid_search: "kb_hybrid_search(\\$1::uuid, '${1:texto}', embed('${1:texto}'), 10)",
  embed: "embed('${1:texto}')",
};

/**
 * Monaco SQL editor with ⌘/Ctrl+Enter to run and completions for the knowledge base's tables, columns and
 * search functions.
 */
export function SqlEditor({
  value,
  onChange,
  onRun,
  schema,
  height = 240,
  ariaLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  onRun: () => void;
  schema?: KbSchema;
  height?: number;
  ariaLabel: string;
}) {
  const { resolvedTheme } = useTheme();
  const runRef = React.useRef(onRun);
  const schemaRef = React.useRef(schema);
  const disposables = React.useRef<{ dispose: () => void }[]>([]);
  React.useEffect(() => {
    runRef.current = onRun;
  }, [onRun]);
  React.useEffect(() => {
    schemaRef.current = schema;
  }, [schema]);
  React.useEffect(() => () => disposables.current.forEach((d) => d.dispose()), []);

  const onMount: OnMount = (editor, monaco: Monaco) => {
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => runRef.current());
    const provider = monaco.languages.registerCompletionItemProvider("sql", {
      provideCompletionItems: (model: editor.ITextModel, position: Position) => {
        const word = model.getWordUntilPosition(position);
        const range = {
          startLineNumber: position.lineNumber,
          endLineNumber: position.lineNumber,
          startColumn: word.startColumn,
          endColumn: word.endColumn,
        };
        const relations = schemaRef.current?.relations ?? [];
        const kinds = monaco.languages.CompletionItemKind;
        const suggestions = [
          ...relations.map((r) => ({
            label: r.name,
            kind: r.kind === "view" ? kinds.Interface : kinds.Struct,
            insertText: r.name,
            detail: r.description || r.kind,
            range,
          })),
          ...relations.flatMap((r) =>
            r.columns.map((c) => ({
              label: c.name,
              kind: kinds.Field,
              insertText: c.name,
              detail: `${r.name}${c.type ? ` · ${c.type}` : ""}`,
              range,
            })),
          ),
          ...Object.entries(FUNCTION_SNIPPETS).map(([fn, snippet]) => ({
            label: fn,
            kind: kinds.Function,
            insertText: snippet,
            insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
            detail: schemaRef.current?.functions.find((f) => f.startsWith(fn)) ?? fn,
            range,
          })),
          ...KEYWORDS.map((k) => ({ label: k, kind: kinds.Keyword, insertText: k, range })),
        ];
        return { suggestions };
      },
    });
    disposables.current.push(provider);
    editor.focus();
  };

  return (
    <div className="overflow-hidden rounded-md border border-border" style={{ height }}>
      <Editor
        height={height}
        language="sql"
        value={value}
        onChange={(v) => onChange(v ?? "")}
        onMount={onMount}
        theme={resolvedTheme === "dark" ? "vs-dark" : "light"}
        loading={<Spinner />}
        options={{
          minimap: { enabled: false },
          fontSize: 13,
          lineNumbers: "on",
          scrollBeyondLastLine: false,
          wordWrap: "on",
          tabSize: 2,
          automaticLayout: true,
          ariaLabel,
          renderLineHighlight: "line",
          padding: { top: 8 },
        }}
      />
    </div>
  );
}
