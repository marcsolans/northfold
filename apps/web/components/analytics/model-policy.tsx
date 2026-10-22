"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  CardHeader,
  ConfirmDialog,
  ErrorState,
  Input,
  PageHeader,
  SkeletonRows,
  Spinner,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  toast,
} from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, CheckCircle2, Plus, X } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { ApiError, http } from "@/lib/api";
import { formatDate, localeTag } from "@/lib/format";
import { useRole } from "@/lib/hooks/use-me";

import { analyticsKeys, useModelPolicy } from "./queries";
import type { ModelPolicy, PolicyIssue } from "./types";

type ListKey = "allow" | "deny";

function sameRules(a: { allow: string[]; deny: string[] }, b: { allow: string[]; deny: string[] }): boolean {
  return JSON.stringify(a.allow) === JSON.stringify(b.allow) && JSON.stringify(a.deny) === JSON.stringify(b.deny);
}

function PatternList({
  list,
  patterns,
  errors,
  editable,
  onChange,
}: {
  list: ListKey;
  patterns: string[];
  errors: PolicyIssue[];
  editable: boolean;
  onChange: (next: string[]) => void;
}) {
  const t = useTranslations("analytics.policy");
  const [draft, setDraft] = React.useState("");
  const add = () => {
    const value = draft.trim();
    if (!value) return;
    if (!patterns.includes(value)) onChange([...patterns, value]);
    setDraft("");
  };
  return (
    <Card className="flex min-w-0 flex-col">
      <CardHeader title={t(`${list}.title`)} description={t(`${list}.description`)} />
      <div className="flex flex-col gap-3 p-4">
        {patterns.length === 0 ? (
          <p className="text-sm text-fg-muted">{t(`${list}.empty`)}</p>
        ) : (
          <ul className="flex flex-wrap gap-1.5">
            {patterns.map((p) => {
              const issue = errors.find((e) => e.field === list && e.pattern === p);
              return (
                <li key={p}>
                  <span
                    className={
                      issue
                        ? "inline-flex items-center gap-1 rounded-sm border border-danger/40 bg-danger-soft px-2 py-0.5 font-mono text-xs text-danger"
                        : "inline-flex items-center gap-1 rounded-sm border border-border bg-subtle px-2 py-0.5 font-mono text-xs text-fg"
                    }
                    title={issue ? t(`errors.${issue.code}`) : undefined}
                  >
                    {p}
                    {editable ? (
                      <button
                        type="button"
                        className="rounded-sm text-fg-subtle hover:text-fg"
                        aria-label={t("removePattern", { pattern: p })}
                        onClick={() => onChange(patterns.filter((x) => x !== p))}
                      >
                        <X className="size-3" />
                      </button>
                    ) : null}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
        {errors
          .filter((e) => e.field === list && e.pattern)
          .map((e) => (
            <p key={`${e.code}-${e.pattern}`} className="text-xs text-danger" role="alert">
              <span className="font-mono">{e.pattern}</span>: {t(`errors.${e.code}`)}
            </p>
          ))}
        {editable ? (
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              add();
            }}
          >
            <Input
              aria-label={t(`${list}.add`)}
              placeholder={list === "allow" ? "anthropic/claude-*" : "anthropic/claude-opus-*"}
              className="font-mono"
              maxLength={200}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            />
            <Button type="submit" variant="secondary" disabled={!draft.trim()}>
              <Plus />
              {t(`${list}.add`)}
            </Button>
          </form>
        ) : null}
      </div>
    </Card>
  );
}

function usePreview(rules: { allow: string[]; deny: string[] }, enabled: boolean) {
  const [debounced, setDebounced] = React.useState(rules);
  React.useEffect(() => {
    const id = window.setTimeout(() => setDebounced(rules), 300);
    return () => window.clearTimeout(id);
  }, [rules]);
  return useQuery({
    queryKey: ["model-policy", "preview", debounced],
    queryFn: () => http.post<ModelPolicy>("/model-policy/preview", debounced),
    enabled,
    placeholderData: (prev) => prev,
  });
}

export function ModelPolicySettings() {
  const t = useTranslations("analytics.policy");
  const ts = useTranslations("settings.sections");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const isAdmin = useRole("admin");
  const policy = useModelPolicy();
  const [rules, setRules] = React.useState<{ allow: string[]; deny: string[] } | null>(null);
  const [confirmReset, setConfirmReset] = React.useState(false);
  const saved = policy.data?.rules ?? null;
  const current = rules ?? saved ?? { allow: [], deny: [] };
  const dirty = saved !== null && rules !== null && !sameRules(rules, saved);
  const preview = usePreview(current, Boolean(saved) && dirty);
  const view: ModelPolicy | undefined = dirty ? (preview.data ?? policy.data) : policy.data;
  const errors = dirty ? (preview.data?.errors ?? []) : [];

  const save = useMutation({
    mutationFn: (body: { allow: string[]; deny: string[] }) => http.put<ModelPolicy>("/model-policy", body),
    onSuccess: (data) => {
      qc.setQueryData(analyticsKeys.policy, data);
      setRules(null);
      setConfirmReset(false);
      toast.success(t("saved"));
    },
    onError: (err) => {
      const details = err instanceof ApiError ? (err.details.errors as PolicyIssue[] | undefined) : undefined;
      toast.error(details?.[0]?.code ? t(`errors.${details[0].code}`) : err instanceof ApiError ? err.message : tc("errorGeneric"));
    },
  });

  const update = (list: ListKey, next: string[]) => setRules({ ...current, [list]: next });
  const blockedTiers = (view?.warnings ?? []).filter((w) => w.code === "tier_blocked");
  const blockedRoles = (view?.warnings ?? []).filter((w) => w.code === "role_blocked");
  const globalError = errors.find((e) => !e.pattern);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={ts("modelPolicy")}
        description={t("description")}
        actions={
          isAdmin ? (
            <>
              {saved && (saved.allow.length > 0 || saved.deny.length > 0) ? (
                <Button variant="secondary" onClick={() => setConfirmReset(true)} disabled={save.isPending}>
                  {t("reset")}
                </Button>
              ) : null}
              {dirty ? (
                <Button variant="ghost" onClick={() => setRules(null)} disabled={save.isPending}>
                  {t("discard")}
                </Button>
              ) : null}
              <Button
                variant="primary"
                onClick={() => save.mutate(current)}
                loading={save.isPending}
                disabled={!dirty || errors.length > 0 || preview.isFetching}
              >
                {tc("save")}
              </Button>
            </>
          ) : null
        }
      />
      {policy.isLoading ? (
        <SkeletonRows rows={6} />
      ) : policy.error ? (
        <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void policy.refetch()} retryLabel={tc("retry")} />
      ) : view ? (
        <>
          {!isAdmin ? <Alert tone="info">{t("readOnly")}</Alert> : null}
          {globalError ? <Alert tone="danger">{t(`errors.${globalError.code}`)}</Alert> : null}
          {blockedTiers.length > 0 ? (
            <Alert tone="warning" title={t("tierWarningTitle")}>
              {t("tierWarning", { tiers: blockedTiers.map((w) => t(`tiers.${w.tier ?? "standard"}`)).join(", ") })}
            </Alert>
          ) : null}
          {blockedRoles.length > 0 ? <Alert tone="warning">{t("roleWarning")}</Alert> : null}
          <div className="grid gap-4 lg:grid-cols-2">
            <PatternList list="allow" patterns={current.allow} errors={errors} editable={isAdmin} onChange={(n) => update("allow", n)} />
            <PatternList list="deny" patterns={current.deny} errors={errors} editable={isAdmin} onChange={(n) => update("deny", n)} />
          </div>
          <Card>
            <CardHeader
              title={t("previewTitle")}
              description={t("previewDescription", { allowed: view.allowed_count, total: view.total })}
              actions={dirty && preview.isFetching ? <Spinner /> : dirty ? <Badge tone="warning">{t("unsaved")}</Badge> : null}
            />
            <div className="overflow-x-auto">
              <Table>
                <THead>
                  <tr>
                    <TH>{t("columns.model")}</TH>
                    <TH className="hidden sm:table-cell">{t("columns.usage")}</TH>
                    <TH>{tc("status")}</TH>
                    <TH className="hidden md:table-cell">{t("columns.reason")}</TH>
                  </tr>
                </THead>
                <TBody>
                  {view.models.map((m) => (
                    <TR key={m.model}>
                      <TD>
                        <span className="font-medium">{m.display_name}</span>
                        <span className="block font-mono text-[11px] text-fg-subtle">{m.model}</span>
                      </TD>
                      <TD className="hidden sm:table-cell">
                        <span className="flex flex-wrap gap-1">
                          {m.tiers.map((tier) => (
                            <Badge key={tier} tone="outline">
                              {t(`tiers.${tier}`)}
                            </Badge>
                          ))}
                          {m.roles.map((role) => (
                            <Badge key={role} tone="outline">
                              {t.has(`roles.${role}`) ? t(`roles.${role}`) : role}
                            </Badge>
                          ))}
                        </span>
                      </TD>
                      <TD>
                        {m.allowed ? (
                          <Badge tone="success">
                            <CheckCircle2 className="size-3" aria-hidden />
                            {t("allowed")}
                          </Badge>
                        ) : (
                          <Badge tone="danger">
                            <Ban className="size-3" aria-hidden />
                            {t("blocked")}
                          </Badge>
                        )}
                      </TD>
                      <TD className="hidden text-fg-muted md:table-cell">
                        {t(`reasons.${m.reason}`)}
                        {m.pattern ? <span className="ml-1 font-mono text-xs">{m.pattern}</span> : null}
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </div>
          </Card>
          <p className="text-xs text-fg-subtle">
            {t("footnote")}
            {policy.data?.updated_at ? ` ${t("updatedAt", { date: formatDate(policy.data.updated_at, locale, true) })}` : ""}
          </p>
        </>
      ) : null}
      <ConfirmDialog
        open={confirmReset}
        onOpenChange={setConfirmReset}
        title={t("resetTitle")}
        description={t("resetDescription")}
        confirmLabel={t("reset")}
        cancelLabel={tc("cancel")}
        loading={save.isPending}
        onConfirm={() => save.mutate({ allow: [], deny: [] })}
      />
    </div>
  );
}
