"use client";

import { Alert, Badge, Button, Card, EmptyState, Input, RadioCards, Select, SkeletonRows } from "@messer/ui";
import { useMutation } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";
import { formatDuration } from "@/lib/format";

import { errorMessage } from "./queries";
import type { KnowledgeBase, SearchMode, SearchResult } from "./types";

const MODES: SearchMode[] = ["hybrid", "vector", "keyword"];

export function SearchTab({ kb }: { kb: KnowledgeBase }) {
  const t = useTranslations("knowledge.search");
  const [query, setQuery] = React.useState("");
  const [mode, setMode] = React.useState<SearchMode>("hybrid");
  const [k, setK] = React.useState("8");

  const search = useMutation({
    mutationFn: () =>
      http.post<SearchResult>(`/knowledge-bases/${kb.id}/search`, { query: query.trim(), mode, k: Number(k) }),
  });
  const maxScore = Math.max(...(search.data?.hits ?? []).map((h) => h.score), 0) || 1;

  return (
    <div className="grid gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
      <form
        className="flex flex-col gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (query.trim()) search.mutate();
        }}
      >
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-2 size-4 text-fg-subtle" aria-hidden />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("placeholder")}
            aria-label={t("placeholder")}
            className="pl-8"
            maxLength={2000}
            autoFocus
          />
        </div>
        <RadioCards
          value={mode}
          onValueChange={(v) => setMode(v as SearchMode)}
          options={MODES.map((m) => ({ value: m, label: t(`modes.${m}`), description: t(`modeHints.${m}`) }))}
        />
        <label className="flex items-center justify-between gap-2 text-sm">
          {t("k")}
          <Select
            aria-label={t("k")}
            className="w-24"
            value={k}
            onValueChange={setK}
            options={["4", "8", "12", "20", "50"].map((v) => ({ value: v, label: v }))}
          />
        </label>
        <Button type="submit" variant="primary" loading={search.isPending} disabled={!query.trim()}>
          {t("run")}
        </Button>
        <p className="text-xs text-fg-subtle">{t("modelHint", { model: kb.embedding_model })}</p>
      </form>

      <div className="flex min-w-0 flex-col gap-2">
        {search.isPending ? (
          <SkeletonRows rows={4} />
        ) : search.error ? (
          <Alert tone="danger">{errorMessage(search.error)}</Alert>
        ) : !search.data ? (
          <EmptyState icon={<Search />} title={t("idleTitle")} description={t("idleDescription")} />
        ) : search.data.hits.length === 0 ? (
          <EmptyState icon={<Search />} title={t("noResults")} description={t("noResultsHint")} />
        ) : (
          <>
            <p className="text-xs text-fg-muted">
              {t("summary", { count: search.data.hits.length, mode: t(`modes.${search.data.mode}`) })} ·{" "}
              <span className="tabular">{formatDuration(search.data.took_ms)}</span>
            </p>
            <ol className="flex flex-col gap-2">
              {search.data.hits.map((hit, i) => {
                const pages =
                  hit.page_from === null
                    ? null
                    : hit.page_to === null || hit.page_to === hit.page_from
                      ? t("page", { page: hit.page_from })
                      : t("pages", { from: hit.page_from, to: hit.page_to });
                return (
                  <li key={hit.chunk_id}>
                    <Card className="flex flex-col gap-2 p-3">
                      <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                        <span className="flex min-w-0 items-center gap-2">
                          <span className="tabular text-fg-subtle">{i + 1}.</span>
                          <span className="truncate font-medium">{hit.filename}</span>
                          {pages ? <span className="text-fg-muted">{pages}</span> : null}
                        </span>
                        <span className="flex items-center gap-2">
                          <span className="h-1 w-16 overflow-hidden rounded-full bg-muted" aria-hidden>
                            <span className="block h-full bg-fg" style={{ width: `${Math.round((hit.score / maxScore) * 100)}%` }} />
                          </span>
                          <Badge tone="outline" className="tabular">
                            {t("score")} {hit.score.toFixed(4)}
                          </Badge>
                        </span>
                      </div>
                      {hit.heading ? <p className="text-xs font-semibold text-fg-muted">{hit.heading}</p> : null}
                      <p className="line-clamp-6 whitespace-pre-line text-sm leading-relaxed">{hit.content}</p>
                    </Card>
                  </li>
                );
              })}
            </ol>
          </>
        )}
      </div>
    </div>
  );
}
