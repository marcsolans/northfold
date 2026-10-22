"use client";

import {
  Alert,
  Button,
  Card,
  CardBody,
  CardHeader,
  CodeBlock,
  ConfirmDialog,
  Dialog,
  DialogContent,
  EmptyState,
  ErrorState,
  Field,
  Input,
  SkeletonRows,
  toast,
} from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Pencil, Plus, Trash2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { useUpgradeDialog } from "@/components/billing";
import { ApiError, http } from "@/lib/api";
import { formatDate, formatRelative, localeTag } from "@/lib/format";
import { useMe } from "@/lib/hooks/use-me";
import { hasRole } from "@/lib/types";

interface ProjectSecret {
  name: string;
  created_at: string;
  updated_at: string;
}

/** Same rules as the API (`routers/secrets.py`). */
const NAME_PATTERN = /^[A-Z][A-Z0-9_]{0,119}$/;
const RESERVED_PREFIXES = ["MESSER_", "ANTHROPIC_", "AWS_"] as const;
const MAX_VALUE = 20_000;

type NameProblem = "required" | "format" | "reserved" | null;

function nameProblem(name: string): NameProblem {
  if (!name) return "required";
  if (!NAME_PATTERN.test(name)) return "format";
  if (RESERVED_PREFIXES.some((p) => name.startsWith(p))) return "reserved";
  return null;
}

const secretsKey = (projectId: string) => ["projects", projectId, "secrets"] as const;

function useSecretErrorText() {
  const t = useTranslations("apiKeys.secrets.errors");
  const tc = useTranslations("common");
  return (err: unknown) => {
    if (err instanceof ApiError) return t.has(err.code) ? t(err.code) : err.message || tc("errorGeneric");
    return tc("errorGeneric");
  };
}

/**
 * Project secrets in the project settings: names and last update, add/replace a value (write-only), delete.
 * Values are encrypted at rest and only reach this project's sandbox as environment variables.
 */
export function SecretsCard({ projectId }: { projectId: string }) {
  const t = useTranslations("apiKeys.secrets");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const me = useMe();
  const canManage = hasRole(me.data, "builder");
  const upgrade = useUpgradeDialog();
  const errorText = useSecretErrorText();

  const secrets = useQuery({
    queryKey: secretsKey(projectId),
    queryFn: () => http.get<ProjectSecret[]>(`/projects/${projectId}/secrets`),
    enabled: canManage,
  });

  const [name, setName] = React.useState("");
  const [value, setValue] = React.useState("");
  const [touched, setTouched] = React.useState(false);
  const [replacing, setReplacing] = React.useState<string | null>(null);
  const [replaceValue, setReplaceValue] = React.useState("");
  const [deleting, setDeleting] = React.useState<string | null>(null);

  const trimmed = name.trim();
  const problem = nameProblem(trimmed);
  const exists = (secrets.data ?? []).some((s) => s.name === trimmed);
  const nameError = touched && problem ? t(`nameErrors.${problem}`) : null;
  const valueError = touched && !value ? t("valueRequired") : null;

  const put = useMutation({
    mutationFn: ({ secretName, secretValue }: { secretName: string; secretValue: string; fromDialog: boolean; existed: boolean }) =>
      http.put<ProjectSecret>(`/projects/${projectId}/secrets/${encodeURIComponent(secretName)}`, { value: secretValue }),
    onSuccess: (saved, vars) => {
      qc.setQueryData(secretsKey(projectId), (prev: ProjectSecret[] | undefined) =>
        [...(prev ?? []).filter((s) => s.name !== saved.name), saved].sort((a, b) => a.name.localeCompare(b.name)),
      );
      toast.success(vars.existed ? t("replaced", { name: saved.name }) : t("added", { name: saved.name }));
      if (vars.fromDialog) {
        setReplacing(null);
        setReplaceValue("");
      } else {
        setName("");
        setValue("");
        setTouched(false);
      }
    },
    onError: (err) => {
      if (!upgrade.handle(err)) toast.error(errorText(err));
    },
  });

  const remove = useMutation({
    mutationFn: (secretName: string) => http.del(`/projects/${projectId}/secrets/${encodeURIComponent(secretName)}`),
    onSuccess: (_data, secretName) => {
      qc.setQueryData(secretsKey(projectId), (prev: ProjectSecret[] | undefined) => (prev ?? []).filter((s) => s.name !== secretName));
      setDeleting(null);
      toast.success(t("deleted", { name: secretName }));
    },
    onError: (err) => {
      setDeleting(null);
      if (!upgrade.handle(err)) toast.error(errorText(err));
    },
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (problem || !value) return;
    put.mutate({ secretName: trimmed, secretValue: value, fromDialog: false, existed: exists });
  };

  let list: React.ReactNode;
  if (!canManage) {
    list = null;
  } else if (secrets.isLoading) {
    list = <SkeletonRows rows={3} />;
  } else if (secrets.error) {
    list = <ErrorState title={tc("errorTitle")} description={t("loadError")} onRetry={() => void secrets.refetch()} retryLabel={tc("retry")} />;
  } else if (!secrets.data?.length) {
    list = <EmptyState icon={<KeyRound />} title={t("empty.title")} description={t("empty.description")} className="py-8" />;
  } else {
    list = (
      <ul className="divide-y divide-border rounded-md border border-border" aria-label={t("listLabel")}>
        {secrets.data.map((s) => (
          <li key={s.name} className="flex flex-wrap items-center gap-2 px-3 py-2">
            <KeyRound className="size-4 shrink-0 text-fg-subtle" aria-hidden />
            <span className="min-w-0 flex-1 break-all font-mono text-sm font-medium">{s.name}</span>
            <span className="text-xs text-fg-muted">
              <time dateTime={s.updated_at} title={formatDate(s.updated_at, locale, true)}>
                {t("updated", { when: formatRelative(s.updated_at, locale) })}
              </time>
            </span>
            <div className="flex gap-1">
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setReplaceValue("");
                  setReplacing(s.name);
                }}
                aria-label={t("replaceFor", { name: s.name })}
              >
                <Pencil />
                <span className="hidden sm:inline">{t("replace")}</span>
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setDeleting(s.name)} aria-label={t("deleteFor", { name: s.name })}>
                <Trash2 />
                <span className="hidden sm:inline">{tc("delete")}</span>
              </Button>
            </div>
          </li>
        ))}
      </ul>
    );
  }

  return (
    <Card>
      <CardHeader title={t("title")} description={t("description")} />
      <CardBody className="flex flex-col gap-4">
        <div className="flex flex-col gap-2 text-sm text-fg-muted">
          <p>{t("scope")}</p>
          <CodeBlock language={t("usageLanguage")} code={t("usageExample")} />
        </div>

        {me.isLoading ? (
          <SkeletonRows rows={2} />
        ) : !canManage ? (
          <Alert tone="info">{t("readOnly")}</Alert>
        ) : (
          <form className="flex flex-col gap-3 rounded-md border border-border p-3" onSubmit={submit} noValidate>
            <p className="text-sm font-medium">{t("addTitle")}</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field
                label={t("name")}
                htmlFor="secret-name"
                error={nameError}
                hint={!nameError && exists && !problem ? t("existsHint") : t("nameHint")}
              >
                <Input
                  id="secret-name"
                  value={name}
                  maxLength={120}
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="CRM_TOKEN"
                  className="font-mono"
                  aria-invalid={Boolean(nameError)}
                  onChange={(e) => setName(e.target.value)}
                  onBlur={() => name && setTouched(true)}
                />
              </Field>
              <Field label={t("value")} htmlFor="secret-value" error={valueError} hint={t("valueHint")}>
                <Input
                  id="secret-value"
                  type="password"
                  value={value}
                  maxLength={MAX_VALUE}
                  autoComplete="new-password"
                  spellCheck={false}
                  aria-invalid={Boolean(valueError)}
                  onChange={(e) => setValue(e.target.value)}
                />
              </Field>
            </div>
            <div className="flex justify-end">
              <Button type="submit" variant="primary" loading={put.isPending && !put.variables?.fromDialog}>
                <Plus />
                {exists && !problem ? t("replaceSubmit") : t("addSubmit")}
              </Button>
            </div>
          </form>
        )}

        {list}
      </CardBody>

      <Dialog
        open={replacing !== null}
        onOpenChange={(open) => {
          if (!open && !put.isPending) setReplacing(null);
        }}
      >
        <DialogContent
          title={t("replaceTitle", { name: replacing ?? "" })}
          description={t("replaceDescription")}
          footer={
            <>
              <Button variant="secondary" onClick={() => setReplacing(null)} disabled={put.isPending}>
                {tc("cancel")}
              </Button>
              <Button
                type="submit"
                form="secret-replace-form"
                variant="primary"
                loading={put.isPending && put.variables?.fromDialog}
                disabled={!replaceValue}
              >
                {tc("save")}
              </Button>
            </>
          }
        >
          <form
            id="secret-replace-form"
            onSubmit={(e) => {
              e.preventDefault();
              if (replacing && replaceValue) put.mutate({ secretName: replacing, secretValue: replaceValue, fromDialog: true, existed: true });
            }}
          >
            <Field label={t("newValue")} htmlFor="secret-replace-value" hint={t("valueHint")}>
              <Input
                id="secret-replace-value"
                type="password"
                value={replaceValue}
                maxLength={MAX_VALUE}
                autoComplete="new-password"
                spellCheck={false}
                autoFocus
                onChange={(e) => setReplaceValue(e.target.value)}
              />
            </Field>
          </form>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => {
          if (!open && !remove.isPending) setDeleting(null);
        }}
        title={t("deleteTitle", { name: deleting ?? "" })}
        description={t("deleteDescription")}
        confirmLabel={tc("delete")}
        cancelLabel={tc("cancel")}
        loading={remove.isPending}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting);
        }}
      />
      {upgrade.dialog}
    </Card>
  );
}
