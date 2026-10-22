"use client";

import {
  Alert,
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  Field,
  Input,
  RadioCards,
  Select,
  SkeletonRows,
  Switch,
  toast,
} from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Database, Folder, FileText, Layers } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { KnowledgeBasePicker } from "@/components/knowledge/knowledge-base-picker";
import { http } from "@/lib/api";

import { connectorKeys, errorMessage } from "./queries";
import type { Connection, Resource, SyncItem } from "./types";

const SCHEDULES: Record<string, string | null> = {
  manual: null,
  every15: "*/15 * * * *",
  hourly: "0 * * * *",
  daily: "0 6 * * *",
  weekly: "0 6 * * 1",
};

function presetFor(schedule: string | null): string {
  if (!schedule) return "manual";
  return Object.entries(SCHEDULES).find(([, v]) => v === schedule)?.[0] ?? "custom";
}

function ResourceIcon({ kind }: { kind: string }) {
  if (kind === "table" || kind === "view") return <Database className="size-4 text-fg-subtle" aria-hidden />;
  if (kind === "object") return <Layers className="size-4 text-fg-subtle" aria-hidden />;
  if (kind === "page" || kind === "database") return <FileText className="size-4 text-fg-subtle" aria-hidden />;
  return <Folder className="size-4 text-fg-subtle" aria-hidden />;
}

function ResourceBrowser({ connectionId, onPick }: { connectionId: string; onPick: (r: Resource) => void }) {
  const t = useTranslations("connectors.syncs");
  const tc = useTranslations("common");
  const [trail, setTrail] = React.useState<Resource[]>([]);
  const parent = trail.length > 0 ? (trail[trail.length - 1]?.id ?? null) : null;
  const resources = useQuery({
    queryKey: connectorKeys.resources(connectionId, parent),
    queryFn: () => http.get<Resource[]>(`/connections/${connectionId}/resources`, { parent: parent ?? undefined }),
    staleTime: 30_000,
  });
  const items = (resources.data ?? []).filter((r) => r.id !== parent);
  return (
    <div className="rounded-md border border-border">
      <div className="flex flex-wrap items-center gap-1 border-b border-border px-2 py-1.5 text-xs text-fg-muted">
        <button type="button" className="hover:text-fg" onClick={() => setTrail([])}>
          {t("browseTitle")}
        </button>
        {trail.map((r, i) => (
          <span key={r.id} className="flex items-center gap-1">
            <ChevronRight className="size-3" aria-hidden />
            <button type="button" className="hover:text-fg" onClick={() => setTrail(trail.slice(0, i + 1))}>
              {r.name}
            </button>
          </span>
        ))}
      </div>
      <div className="max-h-64 overflow-y-auto p-1">
        {resources.isLoading ? (
          <div className="p-2">
            <SkeletonRows rows={3} />
          </div>
        ) : resources.error ? (
          <p className="p-2 text-xs text-danger">{errorMessage(resources.error)}</p>
        ) : items.length === 0 ? (
          <p className="p-2 text-xs text-fg-muted">{t("noResources")}</p>
        ) : (
          items.map((r) => (
            <div key={r.id} className="flex items-center justify-between gap-2 rounded-sm px-2 py-1 hover:bg-subtle">
              <button
                type="button"
                className="flex min-w-0 flex-1 items-center gap-2 text-left text-sm disabled:cursor-default"
                disabled={!r.has_children}
                onClick={() => setTrail([...trail, r])}
              >
                <ResourceIcon kind={r.kind} />
                <span className="truncate">{r.name}</span>
                {r.has_children ? <ChevronRight className="size-3 shrink-0 text-fg-subtle" aria-hidden /> : null}
              </button>
              {r.kind !== "site" ? (
                <Button type="button" size="sm" variant="ghost" onClick={() => onPick(r)}>
                  {t("select")}
                </Button>
              ) : null}
            </div>
          ))
        )}
      </div>
      {trail.length > 0 ? (
        <div className="border-t border-border p-1 text-right">
          <Button type="button" size="sm" variant="ghost" onClick={() => setTrail(trail.slice(0, -1))}>
            {tc("back")}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

export function SyncEditor({
  connection,
  sync,
  open,
  onOpenChange,
}: {
  connection: Connection;
  sync: SyncItem | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {open ? <SyncForm key={sync?.id ?? "new"} connection={connection} sync={sync} onDone={() => onOpenChange(false)} /> : null}
    </Dialog>
  );
}

function SyncForm({ connection, sync, onDone }: { connection: Connection; sync: SyncItem | null; onDone: () => void }) {
  const t = useTranslations("connectors.syncs");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const isDb = connection.category === "database";
  const [kbIds, setKbIds] = React.useState<string[]>(sync ? [sync.kb_id] : []);
  const [resource, setResource] = React.useState(sync?.resource ?? "");
  const [picked, setPicked] = React.useState<Resource | null>(null);
  const [browsing, setBrowsing] = React.useState(!sync);
  const [mode, setMode] = React.useState<"full" | "incremental">(sync?.mode ?? "full");
  const [cursorField, setCursorField] = React.useState(sync?.cursor_field ?? "");
  const [primaryKey, setPrimaryKey] = React.useState((sync?.primary_key ?? []).join(", "));
  const [preset, setPreset] = React.useState(presetFor(sync?.schedule ?? null));
  const [customSchedule, setCustomSchedule] = React.useState(sync?.schedule ?? "");
  const [recursive, setRecursive] = React.useState(sync?.options.recursive !== false);
  const [targetTable, setTargetTable] = React.useState(String(sync?.options.target_table ?? ""));
  const [runNow, setRunNow] = React.useState(!sync);
  const [error, setError] = React.useState<string | null>(null);
  const isFolder = resource.startsWith("folder:") || resource.startsWith("path:");
  const isTable = resource.startsWith("table:") || resource.startsWith("object:");
  const columns = picked?.meta.columns ?? [];

  const pick = (r: Resource) => {
    setResource(r.id);
    setPicked(r);
    setBrowsing(false);
    if (r.meta.primary_key && r.meta.primary_key.length > 0) setPrimaryKey(r.meta.primary_key.join(", "));
    if (typeof r.meta.cursor_field === "string") setCursorField(r.meta.cursor_field);
    else if (r.meta.columns) {
      const guess = r.meta.columns.find((c) => c.kb_type === "timestamp" && /updated|modified|changed/i.test(c.name));
      if (guess) setCursorField(guess.name);
    }
  };

  const save = useMutation({
    mutationFn: async () => {
      const kbId = kbIds[0];
      if (!kbId) throw new Error(t("kbRequired"));
      if (!resource.trim()) throw new Error(t("resourceRequired"));
      const schedule = preset === "custom" ? customSchedule.trim() || null : (SCHEDULES[preset] ?? null);
      const options: Record<string, unknown> = { ...(sync?.options ?? {}) };
      if (isFolder) options.recursive = recursive;
      if (isTable) {
        if (targetTable.trim()) options.target_table = targetTable.trim();
        else delete options.target_table;
      }
      const body = {
        kb_id: kbId,
        resource: resource.trim(),
        mode,
        cursor_field: mode === "incremental" && cursorField.trim() ? cursorField.trim() : null,
        primary_key: primaryKey
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        schedule,
        options,
      };
      if (sync) return http.patch<SyncItem>(`/syncs/${sync.id}`, body);
      return http.post<SyncItem>("/syncs", { ...body, connection_id: connection.id, run_now: runNow });
    },
    onSuccess: (saved) => {
      toast.success(saved.status === "queued" ? t("queued") : t("saved"));
      void qc.invalidateQueries({ queryKey: ["syncs"] });
      void qc.invalidateQueries({ queryKey: connectorKeys.connections });
      onDone();
    },
    onError: (err) => setError(errorMessage(err)),
  });

  return (
    <DialogContent
      wide
      title={sync ? t("edit") : t("new")}
      description={connection.name}
      footer={
        <>
          <Button type="button" variant="secondary" onClick={onDone}>
            {tc("cancel")}
          </Button>
          <Button type="submit" form="sync-form" variant="primary" loading={save.isPending}>
            {tc("save")}
          </Button>
        </>
      }
    >
      <form
        id="sync-form"
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          save.mutate();
        }}
      >
        {error ? <Alert tone="danger">{error}</Alert> : null}
        <Field label={t("kb")}>
          <KnowledgeBasePicker value={kbIds} onChange={setKbIds} multiple={false} />
        </Field>
        <Field label={t("resource")} htmlFor="sync-resource" hint={t("manual")}>
          <div className="flex gap-2">
            <Input
              id="sync-resource"
              value={resource}
              onChange={(e) => {
                setResource(e.target.value);
                setPicked(null);
              }}
              placeholder={t("resourcePlaceholder")}
              className="font-mono text-xs"
              spellCheck={false}
            />
            <Button type="button" variant="secondary" onClick={() => setBrowsing((v) => !v)}>
              {t("browse")}
            </Button>
          </div>
        </Field>
        {browsing ? <ResourceBrowser connectionId={connection.id} onPick={pick} /> : null}

        <Field label={t("mode")} hint={t("modeHint")}>
          <RadioCards
            className="grid-cols-2"
            value={mode}
            onValueChange={(v) => setMode(v === "incremental" ? "incremental" : "full")}
            options={[
              { value: "full", label: t("modes.full") },
              { value: "incremental", label: t("modes.incremental") },
            ]}
          />
        </Field>

        {isDb ? (
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t("primaryKey")} htmlFor="sync-pk" hint={t("primaryKeyHint")}>
              <Input id="sync-pk" value={primaryKey} onChange={(e) => setPrimaryKey(e.target.value)} className="font-mono text-xs" />
            </Field>
            {mode === "incremental" ? (
              <Field label={t("cursorField")} htmlFor="sync-cursor" hint={t("cursorFieldHint")}>
                {columns.length > 0 ? (
                  <Select
                    id="sync-cursor"
                    value={cursorField}
                    onValueChange={setCursorField}
                    options={columns.map((c) => ({ value: c.name, label: c.name, description: c.type }))}
                  />
                ) : (
                  <Input id="sync-cursor" value={cursorField} onChange={(e) => setCursorField(e.target.value)} className="font-mono text-xs" required />
                )}
              </Field>
            ) : null}
          </div>
        ) : null}

        {isFolder ? (
          <label className="flex items-center justify-between gap-3 text-sm">
            <span className="font-medium">{t("recursive")}</span>
            <Switch checked={recursive} onCheckedChange={setRecursive} aria-label={t("recursive")} />
          </label>
        ) : null}
        {isTable ? (
          <Field label={t("targetTable")} htmlFor="sync-target" hint={t("targetTableHint")}>
            <Input id="sync-target" value={targetTable} onChange={(e) => setTargetTable(e.target.value)} className="font-mono text-xs" maxLength={63} />
          </Field>
        ) : null}

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("schedule")} hint={t("scheduleHint")}>
            <Select
              value={preset}
              onValueChange={setPreset}
              options={[...Object.keys(SCHEDULES), "custom"].map((k) => ({ value: k, label: t(`schedules.${k}`) }))}
            />
          </Field>
          {preset === "custom" ? (
            <Field label={t("schedules.custom")} htmlFor="sync-cron">
              <Input id="sync-cron" value={customSchedule} onChange={(e) => setCustomSchedule(e.target.value)} placeholder="0 */6 * * *" className="font-mono text-xs" />
            </Field>
          ) : null}
        </div>
        {!sync ? (
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={runNow} onCheckedChange={(v) => setRunNow(v === true)} />
            {t("runAfterSave")}
          </label>
        ) : null}
      </form>
    </DialogContent>
  );
}
