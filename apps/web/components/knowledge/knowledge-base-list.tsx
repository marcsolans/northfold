"use client";

import { Badge, Button, Card, EmptyState, ErrorState, Input, PageHeader, Skeleton, StatusDot } from "@messer/ui";
import { BookOpen, Database, FileText, Layers, Plus, Search } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { formatRelative, localeTag } from "@/lib/format";
import { useRole } from "@/lib/hooks/use-me";

import { CreateKnowledgeBaseDialog } from "./create-kb-dialog";
import { formatBytes, useKnowledgeBases } from "./queries";
import type { KnowledgeBase } from "./types";

export function GovernanceBadge({ mode }: { mode: KnowledgeBase["governance_mode"] }) {
  const t = useTranslations("knowledge.governance");
  if (mode === "off") return null;
  return <Badge tone={mode === "enforce" ? "accent" : "warning"}>{t(mode)}</Badge>;
}

function KbCard({ kb }: { kb: KnowledgeBase }) {
  const t = useTranslations("knowledge");
  const locale = localeTag(useLocale());
  const s = kb.stats;
  return (
    <Link
      href={`/app/knowledge/${kb.id}`}
      className="group flex flex-col gap-3 rounded-md border border-border bg-surface p-4 transition-colors hover:border-border-strong"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-base font-semibold text-fg group-hover:underline">{kb.name}</p>
          <p className="mt-0.5 line-clamp-2 min-h-[2.5em] text-sm text-fg-muted">{kb.description || t("noDescription")}</p>
        </div>
        <GovernanceBadge mode={kb.governance_mode} />
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fg-muted [&_svg]:size-3.5">
        <span className="tabular flex items-center gap-1">
          <FileText aria-hidden />
          {t("card.files", { count: s.files })}
        </span>
        <span className="tabular flex items-center gap-1">
          <Layers aria-hidden />
          {t("card.chunks", { count: s.chunks })}
        </span>
        <span className="tabular flex items-center gap-1">
          <Database aria-hidden />
          {t("card.tables", { count: s.tables })}
        </span>
        <span className="tabular">{formatBytes(s.size, locale)}</span>
      </div>
      <div className="flex items-center justify-between gap-2 text-xs text-fg-subtle">
        <span className="flex items-center gap-1.5">
          {s.files_processing > 0 ? (
            <>
              <StatusDot tone="info" pulse />
              {t("card.processing", { count: s.files_processing })}
            </>
          ) : s.files_error > 0 ? (
            <>
              <StatusDot tone="danger" />
              {t("card.errors", { count: s.files_error })}
            </>
          ) : (
            <>
              <StatusDot tone="success" />
              {t("card.upToDate")}
            </>
          )}
        </span>
        <span>{formatRelative(kb.updated_at, locale)}</span>
      </div>
    </Link>
  );
}

/** Knowledge bases of the organization (optionally of one project), with search and creation. */
export function KnowledgeBaseList({ projectId, embedded = false }: { projectId?: string | null; embedded?: boolean }) {
  const t = useTranslations("knowledge");
  const tc = useTranslations("common");
  const canCreate = useRole("builder");
  const kbs = useKnowledgeBases(projectId);
  const [query, setQuery] = React.useState("");
  const [createOpen, setCreateOpen] = React.useState(false);

  const filtered = (kbs.data ?? []).filter(
    (kb) => !query.trim() || `${kb.name} ${kb.description}`.toLowerCase().includes(query.trim().toLowerCase()),
  );
  const createButton = canCreate ? (
    <Button variant="primary" onClick={() => setCreateOpen(true)}>
      <Plus />
      {t("newBase")}
    </Button>
  ) : null;

  return (
    <div className="flex flex-col gap-4">
      {embedded ? (
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-md font-semibold">{t("title")}</h2>
          {createButton}
        </div>
      ) : (
        <PageHeader title={t("title")} description={t("description")} actions={createButton} />
      )}
      {(kbs.data?.length ?? 0) > 6 ? (
        <div className="relative max-w-sm">
          <Search className="pointer-events-none absolute left-2.5 top-2 size-4 text-fg-subtle" aria-hidden />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("searchPlaceholder")}
            aria-label={t("searchPlaceholder")}
            className="pl-8"
          />
        </div>
      ) : null}
      {kbs.isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-36" />
          ))}
        </div>
      ) : kbs.error ? (
        <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void kbs.refetch()} retryLabel={tc("retry")} />
      ) : filtered.length === 0 && !query ? (
        <EmptyState
          icon={<BookOpen />}
          title={t("empty.title")}
          description={t("empty.description")}
          action={createButton}
        />
      ) : filtered.length === 0 ? (
        <Card className="p-6 text-center text-sm text-fg-muted">{t("noMatches")}</Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {filtered.map((kb) => (
            <KbCard key={kb.id} kb={kb} />
          ))}
        </div>
      )}
      <CreateKnowledgeBaseDialog open={createOpen} onOpenChange={setCreateOpen} projectId={projectId} />
    </div>
  );
}
