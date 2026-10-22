"use client";

import { Alert, Button, Checkbox, Dialog, DialogContent, Field, Input, Label, Select, Skeleton, toast } from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, Copy } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { isPlanLimitError, useUpgradeDialog } from "@/components/billing";
import { ApiError, http } from "@/lib/api";
import { useProjects } from "@/lib/studio/hooks";

import { type ApiKey, type CreatedApiKey, apiKeysKeys } from "./types";

const ALL_PROJECTS = "__all__";

export function useScopeLabel() {
  const t = useTranslations("apiKeys.scopes");
  return React.useCallback(
    (scope: string) => ({
      label: t.has(`${scope.replace(":", "_")}.label`) ? t(`${scope.replace(":", "_")}.label`) : scope,
      description: t.has(`${scope.replace(":", "_")}.description`) ? t(`${scope.replace(":", "_")}.description`) : null,
    }),
    [t],
  );
}

function ShowOnce({ created, onDone }: { created: CreatedApiKey; onDone: () => void }) {
  const t = useTranslations("apiKeys.created");
  const [copied, setCopied] = React.useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(created.key);
      setCopied(true);
      toast.success(t("copied"));
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error(t("copyFailed"));
    }
  };
  return (
    <div className="flex flex-col gap-4">
      <Alert tone="warning" title={t("warningTitle")}>
        <span className="flex items-start gap-1.5">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
          {t("warning")}
        </span>
      </Alert>
      <Field label={t("keyLabel", { name: created.name })} htmlFor="created-key">
        <div className="flex gap-2">
          <Input
            id="created-key"
            readOnly
            value={created.key}
            className="font-mono text-xs"
            onFocus={(e) => e.currentTarget.select()}
          />
          <Button variant="primary" onClick={() => void copy()}>
            {copied ? <Check /> : <Copy />}
            {copied ? t("copiedShort") : t("copy")}
          </Button>
        </div>
      </Field>
      <p className="text-sm text-fg-muted">{t("usage")}</p>
      <pre className="overflow-x-auto rounded-md border border-border bg-subtle p-3 font-mono text-xs">
        {`Authorization: Bearer ${created.prefix}…`}
      </pre>
      <div className="flex justify-end">
        <Button variant="dark" onClick={onDone}>
          {t("done")}
        </Button>
      </div>
    </div>
  );
}

/** Create an API key (name, optional project, scopes), then show the full key once with copy and a warning. */
export function CreateKeyDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const t = useTranslations("apiKeys.create");
  const te = useTranslations("apiKeys.errors");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const upgrade = useUpgradeDialog();
  const scopeLabel = useScopeLabel();
  const projects = useProjects();
  const scopes = useQuery({
    queryKey: apiKeysKeys.scopes,
    queryFn: () => http.get<string[]>("/api-keys/scopes"),
    staleTime: 60 * 60_000,
    enabled: open,
  });

  const [name, setName] = React.useState("");
  const [projectId, setProjectId] = React.useState(ALL_PROJECTS);
  const [selected, setSelected] = React.useState<ReadonlySet<string>>(() => new Set());
  const [touched, setTouched] = React.useState(false);
  const [created, setCreated] = React.useState<CreatedApiKey | null>(null);

  const create = useMutation({
    mutationFn: () =>
      http.post<CreatedApiKey>("/api-keys", {
        name: name.trim(),
        project_id: projectId === ALL_PROJECTS ? null : projectId,
        scopes: [...selected].sort(),
      }),
    onSuccess: (key) => {
      qc.setQueryData(apiKeysKeys.list, (prev: ApiKey[] | undefined) => {
        const { key: _secret, ...row } = key;
        return [row, ...(prev ?? [])];
      });
      void qc.invalidateQueries({ queryKey: apiKeysKeys.list, exact: true });
      setCreated(key);
    },
    onError: (err) => {
      if (upgrade.handle(err)) onOpenChange(false);
    },
  });

  const { reset } = create;
  React.useEffect(() => {
    if (!open) return;
    setName("");
    setProjectId(ALL_PROJECTS);
    setSelected(new Set());
    setTouched(false);
    setCreated(null);
    reset();
  }, [open, reset]);

  const nameError = touched && !name.trim() ? t("nameRequired") : null;
  const apiError =
    create.error && !isPlanLimitError(create.error)
      ? create.error instanceof ApiError && te.has(create.error.code)
        ? te(create.error.code)
        : create.error instanceof Error
          ? create.error.message || tc("errorGeneric")
          : tc("errorGeneric")
      : null;

  const toggle = (scope: string, on: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(scope);
      else next.delete(scope);
      return next;
    });

  const projectOptions = [
    { value: ALL_PROJECTS, label: t("allProjects") },
    ...(projects.data ?? []).map((p) => ({ value: p.id, label: p.name })),
  ];

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(o) => {
          if (!create.isPending) onOpenChange(o);
        }}
      >
        <DialogContent
          title={created ? t("createdTitle") : t("title")}
          description={created ? undefined : t("description")}
          footer={
            created ? undefined : (
              <>
                <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={create.isPending}>
                  {tc("cancel")}
                </Button>
                <Button type="submit" form="create-key-form" variant="primary" loading={create.isPending}>
                  {t("submit")}
                </Button>
              </>
            )
          }
        >
          {created ? (
            <ShowOnce created={created} onDone={() => onOpenChange(false)} />
          ) : (
            <form
              id="create-key-form"
              className="flex flex-col gap-4"
              noValidate
              onSubmit={(e) => {
                e.preventDefault();
                setTouched(true);
                if (name.trim()) create.mutate();
              }}
            >
              <Field label={t("name")} htmlFor="key-name" error={nameError} hint={t("nameHint")}>
                <Input
                  id="key-name"
                  value={name}
                  maxLength={200}
                  autoComplete="off"
                  placeholder={t("namePlaceholder")}
                  aria-invalid={Boolean(nameError)}
                  onChange={(e) => setName(e.target.value)}
                />
              </Field>
              <Field label={t("project")} htmlFor="key-project" hint={t("projectHint")}>
                {projects.isLoading ? (
                  <Skeleton className="h-8 w-full" />
                ) : (
                  <Select id="key-project" value={projectId} onValueChange={setProjectId} options={projectOptions} />
                )}
              </Field>
              {projects.error ? <Alert tone="warning">{t("projectsError")}</Alert> : null}
              <fieldset className="flex flex-col gap-2">
                <legend className="mb-1 text-sm font-medium">{t("scopes")}</legend>
                <p className="text-xs text-fg-subtle">{t("scopesHint")}</p>
                {scopes.isLoading ? (
                  <Skeleton className="h-32 w-full" />
                ) : scopes.error ? (
                  <Alert tone="danger">{t("scopesError")}</Alert>
                ) : (
                  <ul className="grid gap-2 sm:grid-cols-2">
                    {(scopes.data ?? []).map((scope) => {
                      const id = `scope-${scope.replace(/[^a-z0-9]/gi, "-")}`;
                      const info = scopeLabel(scope);
                      return (
                        <li key={scope} className="flex items-start gap-2 rounded-md border border-border px-3 py-2">
                          <Checkbox
                            id={id}
                            checked={selected.has(scope)}
                            onCheckedChange={(v) => toggle(scope, v === true)}
                            className="mt-0.5"
                          />
                          <div className="min-w-0">
                            <Label htmlFor={id} className="flex flex-wrap items-center gap-1.5">
                              {info.label}
                              <span className="font-mono text-xs font-normal text-fg-subtle">{scope}</span>
                            </Label>
                            {info.description ? <p className="text-xs text-fg-muted">{info.description}</p> : null}
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                )}
                {selected.size === 0 && !scopes.isLoading && !scopes.error ? (
                  <p className="text-xs text-warning">{t("noScopesWarning")}</p>
                ) : null}
              </fieldset>
              {apiError ? <Alert tone="danger">{apiError}</Alert> : null}
            </form>
          )}
        </DialogContent>
      </Dialog>
      {upgrade.dialog}
    </>
  );
}
