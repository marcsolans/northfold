"use client";

import { Badge, Card, EmptyState, ErrorState, Field, PageHeader, Select, SkeletonRows, Switch, cn } from "@messer/ui";
import { useQuery } from "@tanstack/react-query";
import { CheckSquare, Clock } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";

import { http } from "@/lib/api";
import { formatRelative, localeTag } from "@/lib/format";
import { useProjects } from "@/lib/studio/hooks";
import type { ApprovalPage, ApprovalStatus } from "@/lib/studio/types";

import { ApprovalDrawer } from "./approval-drawer";
import { ApprovalStatusBadge } from "./approval-status-badge";

const STATUSES: (ApprovalStatus | "all")[] = ["pending", "approved", "denied", "expired", "all"];

export function ApprovalsInbox() {
  const t = useTranslations("approvals");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const projects = useProjects();

  const status = (params.get("status") as ApprovalStatus | "all" | null) ?? "pending";
  const projectId = params.get("project") ?? "";
  const agent = params.get("agent") ?? "";
  const mine = params.get("mine") === "1";
  const openId = params.get("id");

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(key, value);
    else next.delete(key);
    const qs = next.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  };

  const approvals = useQuery({
    queryKey: ["approvals", { status, projectId, mine }],
    queryFn: () =>
      http.get<ApprovalPage>("/approvals", {
        status: STATUSES.includes(status) ? status : "pending",
        project_id: projectId || undefined,
        mine: mine || undefined,
        limit: 200,
      }),
    refetchInterval: 30_000,
  });

  const all = approvals.data?.items ?? [];
  const agents = [...new Set(all.map((a) => a.workforce_name))].sort();
  const items = all
    .filter((a) => !agent || a.workforce_name === agent)
    .sort((a, b) => {
      const pa = a.status === "pending" ? 0 : 1;
      const pb = b.status === "pending" ? 0 : 1;
      return pa !== pb ? pa - pb : new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    });

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-8 md:px-8">
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            {t("title")}
            {approvals.data && approvals.data.pending > 0 ? (
              <Badge tone="accent" aria-label={t("pendingCount", { count: approvals.data.pending })}>
                {approvals.data.pending}
              </Badge>
            ) : null}
          </span>
        }
        description={t("description")}
      />
      <Card className="mb-4 p-3">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label={t("filters.status")} htmlFor="a-status">
            <Select
              id="a-status"
              aria-label={t("filters.status")}
              value={status}
              onValueChange={(v) => setParam("status", v === "pending" ? null : v)}
              options={STATUSES.map((s) => ({ value: s, label: s === "all" ? tc("all") : t(`status.${s}`) }))}
            />
          </Field>
          <Field label={t("filters.project")} htmlFor="a-project">
            <Select
              id="a-project"
              aria-label={t("filters.project")}
              value={projectId || "all"}
              onValueChange={(v) => setParam("project", v === "all" ? null : v)}
              options={[{ value: "all", label: tc("all") }, ...(projects.data ?? []).map((p) => ({ value: p.id, label: p.name }))]}
            />
          </Field>
          <Field label={t("filters.agent")} htmlFor="a-agent">
            <Select
              id="a-agent"
              aria-label={t("filters.agent")}
              value={agent || "all"}
              onValueChange={(v) => setParam("agent", v === "all" ? null : v)}
              options={[
                { value: "all", label: tc("all") },
                ...[...new Set([...agents, ...(agent ? [agent] : [])])].map((name) => ({ value: name, label: name })),
              ]}
            />
          </Field>
          <div className="flex items-end pb-1.5">
            <label htmlFor="a-mine" className="flex items-center gap-2 text-sm">
              <Switch id="a-mine" checked={mine} onCheckedChange={(on) => setParam("mine", on ? "1" : null)} />
              {t("filters.mine")}
            </label>
          </div>
        </div>
      </Card>

      <Card>
        {approvals.isLoading ? (
          <div className="p-4">
            <SkeletonRows rows={5} />
          </div>
        ) : approvals.error ? (
          <div className="p-4">
            <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void approvals.refetch()} retryLabel={tc("retry")} />
          </div>
        ) : items.length === 0 ? (
          <div className="p-4">
            <EmptyState
              icon={<CheckSquare />}
              title={status === "pending" ? t("empty.pendingTitle") : t("empty.title")}
              description={status === "pending" ? t("empty.pendingDescription") : t("empty.description")}
            />
          </div>
        ) : (
          <ul className="divide-y divide-border">
            {items.map((a) => {
              const expiresSoon =
                a.status === "pending" && a.expires_at !== null && new Date(a.expires_at).getTime() - Date.now() < 3_600_000;
              return (
                <li key={a.id}>
                  <button
                    type="button"
                    onClick={() => setParam("id", a.id)}
                    aria-current={openId === a.id ? "true" : undefined}
                    className={cn(
                      "flex w-full flex-col gap-1.5 px-4 py-3 text-left hover:bg-subtle sm:flex-row sm:items-center sm:gap-4",
                      openId === a.id && "bg-subtle",
                    )}
                  >
                    <span className="shrink-0">
                      <ApprovalStatusBadge status={a.status} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">{a.title || t("fallbackTitle", { tool: a.tool_name })}</span>
                      <span className="block truncate text-xs text-fg-muted">
                        {a.project_name ?? "—"} · <span className="font-mono">{a.workforce_name}</span> · <span className="font-mono">{a.tool_name}</span>
                      </span>
                    </span>
                    <span className="flex shrink-0 items-center gap-3 text-xs text-fg-subtle">
                      {a.status === "pending" && !a.can_decide ? <Badge tone="outline">{t("needsRole", { role: tc(`roles.${a.assigned_role}`) })}</Badge> : null}
                      {a.status === "pending" && a.expires_at ? (
                        <span className={cn("flex items-center gap-1", expiresSoon && "text-warning")}>
                          <Clock className="size-3.5" aria-hidden />
                          {t("expires", { when: formatRelative(a.expires_at, locale) })}
                        </span>
                      ) : null}
                      <time dateTime={a.created_at}>{formatRelative(a.created_at, locale)}</time>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </Card>
      <ApprovalDrawer approvalId={openId} onClose={() => setParam("id", null)} />
    </div>
  );
}
