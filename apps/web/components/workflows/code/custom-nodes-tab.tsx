"use client";

import {
  Alert,
  Badge,
  Button,
  ConfirmDialog,
  Dialog,
  DialogContent,
  EmptyState,
  Field,
  Input,
  StatusDot,
  toast,
} from "@messer/ui";
import { useMutation } from "@tanstack/react-query";
import { Code2, Plus, Save, Trash2, Undo2 } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { CodeEditor, type CodeMarker } from "@/components/studio/monaco";
import { ApiError, http } from "@/lib/api";
import { errorMessage } from "@/lib/studio/hooks";
import { workflowPath } from "@/lib/workflows/hooks";
import type { CustomNodes } from "@/lib/workflows/types";

const NAME = /^[a-z][a-z0-9_]{0,62}$/;

/** nodes.py: Python functions that appear in the palette as custom nodes. */
export function CustomNodesTab({
  projectId,
  workflow,
  path,
  value,
  canBuild,
  usedBy,
  onSaved,
  onDirtyChange,
}: {
  projectId: string;
  workflow: string;
  path: string;
  value: CustomNodes;
  canBuild: boolean;
  usedBy: Record<string, string[]>;
  onSaved: (next: CustomNodes) => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const t = useTranslations("workflows.custom");
  const tc = useTranslations("common");
  const base = `${workflowPath(projectId, workflow)}/custom-nodes`;
  const [code, setCode] = React.useState(value.code);
  const [problem, setProblem] = React.useState<{ message: string; line: number | null } | null>(
    value.error ? { message: value.error.message, line: value.error.line } : null,
  );
  const [creating, setCreating] = React.useState(false);
  const [newName, setNewName] = React.useState("");
  const [newDescription, setNewDescription] = React.useState("");
  const [removing, setRemoving] = React.useState<string | null>(null);
  const saved = React.useRef(value.code);

  React.useEffect(() => {
    if (value.code !== saved.current) {
      saved.current = value.code;
      setCode(value.code);
    }
  }, [value.code]);
  const dirty = code !== saved.current;
  React.useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);

  const adopt = (next: CustomNodes, message: string) => {
    saved.current = next.code;
    setCode(next.code);
    setProblem(null);
    onSaved(next);
    toast.success(message);
  };

  const save = useMutation({
    mutationFn: () => http.put<CustomNodes>(base, { code }),
    onSuccess: (next) => adopt(next, t("saved")),
    onError: (err) => {
      if (err instanceof ApiError && err.code === "syntax_error") {
        setProblem({ message: err.message, line: typeof err.details.line === "number" ? err.details.line : null });
      } else {
        toast.error(errorMessage(err, tc("errorGeneric")));
      }
    },
  });

  const add = useMutation({
    mutationFn: () => http.post<CustomNodes>(base, { name: newName.trim(), description: newDescription.trim() }),
    onSuccess: (next) => {
      setCreating(false);
      setNewName("");
      setNewDescription("");
      adopt(next, t("added"));
    },
    onError: (err) => toast.error(errorMessage(err, tc("errorGeneric"))),
  });

  const remove = useMutation({
    mutationFn: (name: string) => http.del<CustomNodes>(`${base}/${encodeURIComponent(name)}`),
    onSuccess: (next) => {
      setRemoving(null);
      adopt(next, t("removed"));
    },
    onError: (err) => toast.error(errorMessage(err, tc("errorGeneric"))),
  });

  const markers = React.useMemo<CodeMarker[]>(
    () => (problem?.line ? [{ line: problem.line, message: problem.message }] : []),
    [problem],
  );
  const nameInvalid = newName.length > 0 && !NAME.test(newName);

  return (
    <div className="flex h-full min-h-[28rem] flex-col lg:flex-row">
      <aside className="border-b border-border p-3 lg:w-72 lg:shrink-0 lg:border-b-0 lg:border-r" aria-label={t("functions")}>
        <div className="mb-2 flex items-center justify-between gap-2">
          <p className="text-sm font-semibold">{t("functions")}</p>
          {canBuild ? (
            <Button size="sm" variant="secondary" onClick={() => setCreating(true)} disabled={dirty}>
              <Plus />
              {t("new")}
            </Button>
          ) : null}
        </div>
        <p className="mb-3 text-[11px] leading-4 text-fg-subtle">{t("hint")}</p>
        {value.functions.length === 0 ? (
          <EmptyState icon={<Code2 />} title={t("empty.title")} description={t("empty.description")} />
        ) : (
          <ul className="space-y-1.5">
            {value.functions.map((fn) => {
              const users = usedBy[fn.name] ?? [];
              return (
                <li key={fn.name} className="rounded-md border border-border p-2">
                  <div className="flex items-center gap-2">
                    <code className="min-w-0 flex-1 truncate font-mono text-xs font-semibold">{fn.name}</code>
                    {fn.is_async ? <Badge tone="outline">async</Badge> : null}
                    {canBuild ? (
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label={t("remove", { name: fn.name })}
                        disabled={dirty || users.length > 0}
                        title={users.length ? t("inUse", { nodes: users.join(", ") }) : undefined}
                        onClick={() => setRemoving(fn.name)}
                      >
                        <Trash2 />
                      </Button>
                    ) : null}
                  </div>
                  <p className="mt-0.5 font-mono text-[11px] text-fg-subtle">
                    ({fn.params.map((p) => `${p.name}${p.required ? "" : "?"}`).join(", ")})
                  </p>
                  {fn.description ? <p className="mt-1 text-[11px] text-fg-muted">{fn.description}</p> : null}
                  {users.length ? <p className="mt-1 text-[11px] text-fg-subtle">{t("usedBy", { nodes: users.join(", ") })}</p> : null}
                </li>
              );
            })}
          </ul>
        )}
      </aside>
      <div className="flex min-h-[24rem] flex-1 flex-col">
        <div className="flex flex-wrap items-center gap-2 px-4 py-2.5">
          <code className="flex-1 font-mono text-[11px] text-fg-subtle">{path}</code>
          {dirty ? (
            <Badge tone="warning">
              <StatusDot tone="warning" />
              {t("unsaved")}
            </Badge>
          ) : null}
          {canBuild ? (
            <>
              {dirty ? (
                <Button size="sm" variant="ghost" onClick={() => setCode(saved.current)}>
                  <Undo2 />
                  {t("discard")}
                </Button>
              ) : null}
              <Button size="sm" variant="primary" loading={save.isPending} disabled={!dirty} onClick={() => save.mutate()}>
                <Save />
                {t("save")}
              </Button>
            </>
          ) : null}
        </div>
        {problem ? (
          <div className="px-4 pb-2">
            <Alert tone="danger" title={t("syntaxError")}>
              {problem.message}
            </Alert>
          </div>
        ) : null}
        <div className="min-h-0 flex-1 border-y border-border">
          <CodeEditor
            path={path}
            value={code}
            onChange={(next) => {
              setCode(next);
              if (problem) setProblem(null);
            }}
            onSave={() => {
              if (dirty && canBuild) save.mutate();
            }}
            readOnly={!canBuild}
            markers={markers}
            ariaLabel={t("editorLabel", { path })}
          />
        </div>
      </div>

      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent
          title={t("newTitle")}
          description={t("newDescription")}
          footer={
            <>
              <Button variant="ghost" onClick={() => setCreating(false)}>
                {tc("cancel")}
              </Button>
              <Button variant="primary" loading={add.isPending} disabled={!NAME.test(newName)} onClick={() => add.mutate()}>
                {tc("create")}
              </Button>
            </>
          }
        >
          <div className="space-y-3">
            <Field label={t("name")} htmlFor="custom-node-name" error={nameInvalid ? t("nameInvalid") : undefined}>
              <Input id="custom-node-name" value={newName} className="font-mono" onChange={(e) => setNewName(e.target.value)} autoFocus />
            </Field>
            <Field label={tc("description")} htmlFor="custom-node-description">
              <Input id="custom-node-description" value={newDescription} maxLength={300} onChange={(e) => setNewDescription(e.target.value)} />
            </Field>
          </div>
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => {
          if (!open) setRemoving(null);
        }}
        title={t("removeTitle", { name: removing ?? "" })}
        description={t("removeDescription")}
        confirmLabel={tc("delete")}
        cancelLabel={tc("cancel")}
        destructive
        loading={remove.isPending}
        onConfirm={() => {
          if (removing) remove.mutate(removing);
        }}
      />
    </div>
  );
}
