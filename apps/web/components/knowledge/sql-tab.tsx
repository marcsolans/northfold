"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  CodeBlock,
  Dialog,
  DialogContent,
  Field,
  Input,
  Kbd,
  Select,
  SkeletonRows,
  Switch,
  Textarea,
} from "@messer/ui";
import { useMutation } from "@tanstack/react-query";
import { ChevronRight, Play, Plus, ShieldAlert, X } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { ApiError, http } from "@/lib/api";
import { formatDuration } from "@/lib/format";

import { errorMessage, useKbSchema } from "./queries";
import { ResultsGrid } from "./results-grid";
import { SqlEditor } from "./sql-editor";
import type { KnowledgeBase, QueryResult } from "./types";

type ParamType = "text" | "number" | "boolean" | "json";
interface Param {
  type: ParamType;
  value: string;
}

function parseParam(p: Param): unknown {
  if (p.type === "number") {
    const n = Number(p.value.replace(",", "."));
    if (Number.isNaN(n)) throw new Error(p.value);
    return n;
  }
  if (p.type === "boolean") return p.value === "true";
  if (p.type === "json") return JSON.parse(p.value) as unknown;
  return p.value;
}

function storageKey(kbId: string) {
  return `messer:kb-sql:${kbId}`;
}

export function SqlTab({ kb, isAdmin }: { kb: KnowledgeBase; isAdmin: boolean }) {
  const t = useTranslations("knowledge.sql");
  const tc = useTranslations("common");
  const schema = useKbSchema(kb.id);
  const [sql, setSql] = React.useState("SELECT filename, status, chunk_count\nFROM documents\nORDER BY created_at DESC\nLIMIT 20;");
  const [params, setParams] = React.useState<Param[]>([]);
  const [explain, setExplain] = React.useState(false);
  const [limit, setLimit] = React.useState(1000);
  const [breakGlassOpen, setBreakGlassOpen] = React.useState(false);
  const [reason, setReason] = React.useState("");
  const [paramError, setParamError] = React.useState<string | null>(null);

  React.useEffect(() => {
    try {
      const saved = window.localStorage.getItem(storageKey(kb.id));
      if (saved) setSql(saved);
    } catch {
      // storage unavailable (private mode): keep the default query
    }
  }, [kb.id]);
  React.useEffect(() => {
    const id = window.setTimeout(() => {
      try {
        window.localStorage.setItem(storageKey(kb.id), sql);
      } catch {
        // ignore quota/private mode
      }
    }, 400);
    return () => window.clearTimeout(id);
  }, [kb.id, sql]);

  const run = useMutation({
    mutationFn: (opts: { breakGlass?: string }) => {
      const values = params.map(parseParam);
      return http.post<QueryResult>(`/knowledge-bases/${kb.id}/query`, {
        sql,
        params: values,
        explain,
        limit,
        break_glass: opts.breakGlass ? { reason: opts.breakGlass } : null,
      });
    },
  });

  const execute = React.useCallback(
    (breakGlass?: string) => {
      setParamError(null);
      try {
        params.forEach(parseParam);
      } catch {
        setParamError(t("paramInvalid"));
        return;
      }
      run.mutate({ breakGlass });
    },
    [params, run, t],
  );

  const insertExample = (example: "join" | "embed" | "hybrid") => {
    const firstTable = schema.data?.relations.find((r) => r.kind === "table");
    if (example === "join" && firstTable) {
      setSql(
        `-- ${t("examples.join")}\nSELECT t.*, d.filename, d.score\nFROM ${firstTable.name} t\nJOIN kb_text_search($1::uuid, 'texto', 10) d ON true\nLIMIT 50;`,
      );
    } else if (example === "embed") {
      setSql(`-- ${t("examples.embed")}\nSELECT filename, heading, score\nFROM kb_vector_search($1::uuid, embed('texto a buscar'), 10);`);
    } else {
      setSql(
        `-- ${t("examples.hybrid")}\nSELECT filename, page_from, page_to, score, left(content, 200) AS extracto\nFROM kb_hybrid_search($1::uuid, 'texto a buscar', embed('texto a buscar'), 10);`,
      );
    }
    setParams([{ type: "text", value: kb.id }]);
  };

  const result = run.data;
  const error = run.error;
  const position = error instanceof ApiError ? (error.details.position as number | undefined) : undefined;
  const hint = error instanceof ApiError ? (error.details.hint as string | undefined) : undefined;

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_16rem]">
      <div className="flex min-w-0 flex-col gap-3">
        <SqlEditor value={sql} onChange={setSql} onRun={() => execute()} schema={schema.data} ariaLabel={t("editor")} />
        <div className="flex flex-col gap-2">
          {params.map((p, i) => (
            <div key={i} className="flex items-center gap-2">
              <span className="w-8 font-mono text-xs text-fg-subtle">${i + 1}</span>
              <Select
                aria-label={t("paramType")}
                className="w-32"
                value={p.type}
                onValueChange={(v) => setParams((prev) => prev.map((x, j) => (j === i ? { ...x, type: v as ParamType } : x)))}
                options={(["text", "number", "boolean", "json"] as const).map((v) => ({ value: v, label: t(`paramTypes.${v}`) }))}
              />
              <Input
                aria-label={t("paramValue", { n: i + 1 })}
                value={p.value}
                onChange={(e) => setParams((prev) => prev.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))}
                className="font-mono"
              />
              <Button size="icon-sm" variant="ghost" aria-label={tc("remove")} onClick={() => setParams((prev) => prev.filter((_, j) => j !== i))}>
                <X />
              </Button>
            </div>
          ))}
          {paramError ? <Alert tone="danger">{paramError}</Alert> : null}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <Button size="sm" variant="ghost" onClick={() => setParams((prev) => [...prev, { type: "text", value: "" }])}>
              <Plus />
              {t("addParam")}
            </Button>
            <label className="flex items-center gap-2 text-sm">
              <Switch checked={explain} onCheckedChange={setExplain} aria-label={t("explain")} />
              {t("explain")}
            </label>
            <label className="flex items-center gap-2 text-sm text-fg-muted">
              {t("limit")}
              <Input
                type="number"
                min={1}
                max={10000}
                value={limit}
                onChange={(e) => setLimit(Math.max(1, Math.min(10000, Number(e.target.value) || 1)))}
                className="h-7 w-24"
                aria-label={t("limit")}
              />
            </label>
          </div>
          <div className="flex items-center gap-2">
            {isAdmin ? (
              <Button size="sm" variant="ghost" onClick={() => setBreakGlassOpen(true)}>
                <ShieldAlert />
                {t("breakGlass")}
              </Button>
            ) : null}
            <span className="hidden text-xs text-fg-subtle sm:inline">
              <Kbd>⌘</Kbd> <Kbd>Enter</Kbd>
            </span>
            <Button variant="primary" onClick={() => execute()} loading={run.isPending}>
              <Play />
              {t("run")}
            </Button>
          </div>
        </div>

        {run.isPending ? (
          <SkeletonRows rows={3} />
        ) : error ? (
          <Alert tone="danger" title={t("error")}>
            <span className="block font-mono text-xs">{errorMessage(error)}</span>
            {position ? <span className="block text-xs">{t("errorPosition", { position })}</span> : null}
            {hint ? <span className="block text-xs">{hint}</span> : null}
          </Alert>
        ) : result ? (
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2 text-xs text-fg-muted">
              <Badge tone="success">{t("ok")}</Badge>
              <span className="tabular">{formatDuration(result.elapsed_ms)}</span>
              {result.truncated ? <Badge tone="warning">{t("truncated", { limit })}</Badge> : null}
              {result.policy?.break_glass ? <Badge tone="danger">{t("breakGlassActive")}</Badge> : null}
            </div>
            {result.policy?.applied?.length ? (
              <Alert tone="info" title={t("policyApplied")}>
                {result.policy.applied.map((p) => p.relation).join(", ")}
              </Alert>
            ) : null}
            {result.policy?.would_apply?.length ? (
              <Alert tone="warning" title={t("policyShadow")}>
                {result.policy.would_apply.map((p) => p.relation).join(", ")}
              </Alert>
            ) : null}
            {result.plan !== undefined && result.plan !== null ? (
              <CodeBlock code={JSON.stringify(result.plan, null, 2)} language="EXPLAIN (FORMAT JSON)" />
            ) : result.columns.length === 0 ? (
              <p className="text-sm text-fg-muted">{t("noColumns")}</p>
            ) : result.rows.length === 0 ? (
              <Card className="p-4 text-sm text-fg-muted">{t("noRows")}</Card>
            ) : (
              <ResultsGrid columns={result.columns} columnTypes={result.column_types} rows={result.rows} />
            )}
          </div>
        ) : (
          <p className="text-sm text-fg-subtle">{t("idle")}</p>
        )}
      </div>

      <aside className="flex flex-col gap-3">
        <Card className="p-3">
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-fg-subtle">{t("schema")}</p>
          {schema.isLoading ? (
            <SkeletonRows rows={3} />
          ) : schema.error ? (
            <p className="text-xs text-danger">{errorMessage(schema.error)}</p>
          ) : (
            <ul className="flex max-h-80 flex-col gap-1 overflow-y-auto text-xs">
              {(schema.data?.relations ?? []).map((rel) => (
                <li key={rel.name}>
                  <details>
                    <summary className="flex cursor-pointer items-center gap-1 font-mono text-fg [&::-webkit-details-marker]:hidden">
                      <ChevronRight className="size-3 text-fg-subtle" aria-hidden />
                      {rel.name}
                      {rel.kind === "view" ? <span className="text-fg-subtle">· {t("view")}</span> : null}
                    </summary>
                    <ul className="ml-4 mt-1 flex flex-col gap-0.5">
                      {rel.columns.map((c) => (
                        <li key={c.name} className="flex justify-between gap-2 font-mono text-fg-muted">
                          <span className="truncate">{c.name}</span>
                          <span className="text-fg-subtle">{c.type}</span>
                        </li>
                      ))}
                    </ul>
                  </details>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card className="p-3">
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-fg-subtle">{t("functions")}</p>
          <ul className="flex flex-col gap-1 font-mono text-[11px] text-fg-muted">
            {(schema.data?.functions ?? []).map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
          <p className="mb-1 mt-3 text-xs font-medium uppercase tracking-wide text-fg-subtle">{t("examplesTitle")}</p>
          <div className="flex flex-col items-start gap-1">
            <Button size="sm" variant="link" onClick={() => insertExample("hybrid")}>
              {t("examples.hybrid")}
            </Button>
            <Button size="sm" variant="link" onClick={() => insertExample("embed")}>
              {t("examples.embed")}
            </Button>
            {schema.data?.relations.some((r) => r.kind === "table") ? (
              <Button size="sm" variant="link" onClick={() => insertExample("join")}>
                {t("examples.join")}
              </Button>
            ) : null}
          </div>
          <p className="mt-3 text-xs text-fg-subtle">{t("readOnlyHint")}</p>
        </Card>
      </aside>

      <Dialog open={breakGlassOpen} onOpenChange={setBreakGlassOpen}>
        <DialogContent title={t("breakGlassTitle")} description={t("breakGlassDescription")}>
          <form
            className="flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              setBreakGlassOpen(false);
              execute(reason.trim());
            }}
          >
            <Field label={t("breakGlassReason")} htmlFor="break-glass-reason" hint={t("breakGlassHint")}>
              <Textarea id="break-glass-reason" value={reason} onChange={(e) => setReason(e.target.value)} minLength={5} maxLength={500} required />
            </Field>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="secondary" onClick={() => setBreakGlassOpen(false)}>
                {tc("cancel")}
              </Button>
              <Button type="submit" variant="primary" disabled={reason.trim().length < 5}>
                {t("breakGlassRun")}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
