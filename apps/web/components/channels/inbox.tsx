"use client";

import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, PageHeader, Select, SkeletonRows, cn } from "@messer/ui";
import { useInfiniteQuery } from "@tanstack/react-query";
import { FilterX, Inbox as InboxIcon, MessagesSquare, RefreshCw } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";
import { formatRelative, localeTag } from "@/lib/format";
import { useRole } from "@/lib/hooks/use-me";

import { ConversationView } from "./conversation-view";
import { channelKeys, useChannels } from "./hooks";
import { ProviderIcon, useProviderLabel } from "./provider-icon";
import type { ConversationItem, ConversationPage } from "./types";

const PAGE_SIZE = 30;

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = React.useState(value);
  React.useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

function Row({ item, active, href }: { item: ConversationItem; active: boolean; href: string }) {
  const t = useTranslations("channels.inbox");
  const locale = localeTag(useLocale());
  const label = useProviderLabel();
  const last = item.last_message;
  return (
    <li>
      <Link
        href={href}
        scroll={false}
        aria-current={active ? "true" : undefined}
        className={cn(
          "flex gap-3 border-b border-border px-3 py-2.5 hover:bg-subtle",
          active && "bg-subtle shadow-[inset_2px_0_0_0_var(--color-accent)]",
        )}
      >
        <ProviderIcon provider={item.provider} size="sm" className="mt-0.5" />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-2">
            <span className={cn("truncate text-sm", item.status === "open" ? "font-semibold text-fg" : "text-fg-muted")} title={item.contact_id}>
              {item.contact_name || item.contact_id}
            </span>
            <span className="tabular shrink-0 text-[11px] text-fg-subtle">{formatRelative(item.updated_at, locale)}</span>
          </div>
          <p className="truncate text-xs text-fg-muted">
            {last ? `${last.role === "assistant" ? `${item.workforce_name}: ` : ""}${last.text}` : item.title || t("noPreview")}
          </p>
          <div className="mt-1 flex flex-wrap gap-1">
            <span className="text-[11px] text-fg-subtle">{item.channel_name ?? label(item.provider)}</span>
            {item.pending_approvals ? <Badge tone="warning">{t("pendingBadge", { count: item.pending_approvals })}</Badge> : null}
            {item.failed_deliveries ? <Badge tone="danger">{t("failedBadge", { count: item.failed_deliveries })}</Badge> : null}
            {item.status === "closed" ? <Badge tone="neutral">{t("statuses.closed")}</Badge> : null}
            {item.simulated ? <Badge tone="outline">{t("simulated")}</Badge> : null}
          </div>
        </div>
      </Link>
    </li>
  );
}

/** Conversations inbox: threads from every channel of the project, with the selected thread on the right. */
export function Inbox({ projectId, selectedId }: { projectId: string; selectedId?: string }) {
  const t = useTranslations("channels.inbox");
  const tc = useTranslations("common");
  const label = useProviderLabel();
  const canBuild = useRole("builder");
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const channels = useChannels(projectId);
  const provider = params.get("provider") ?? "";
  const status = params.get("status") ?? "";
  const channel = params.get("channel") ?? "";
  const [search, setSearch] = React.useState(params.get("q") ?? "");
  const q = useDebounced(search.trim(), 300);
  const selected = selectedId ?? params.get("c");
  const base = `/app/projects/${projectId}/conversations`;

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params.toString());
    if (value && value !== "all") next.set(key, value);
    else next.delete(key);
    const qs = next.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  };
  React.useEffect(() => {
    if ((params.get("q") ?? "") !== q) setParam("q", q);
    // Only sync the debounced search box to the URL.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  const filters = { provider: provider || undefined, status: status || undefined, channel_id: channel || undefined, q: q || undefined };
  const list = useInfiniteQuery({
    queryKey: [...channelKeys.inbox(projectId), filters],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) =>
      http.get<ConversationPage>(`/projects/${projectId}/conversations`, { ...filters, cursor: pageParam, limit: PAGE_SIZE }, signal),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    refetchInterval: 20_000,
  });
  const items = list.data?.pages.flatMap((p) => p.items) ?? [];
  const facets = list.data?.pages[0]?.providers ?? [];
  const anyFilter = Boolean(provider || status || channel || q);
  const backParams = new URLSearchParams(params.toString());
  backParams.delete("c");
  const backHref = `${base}${backParams.toString() ? `?${backParams.toString()}` : ""}`;
  // Selecting keeps the list mounted (same route, ``?c=``); /conversations/<id> deep links work too.
  const hrefFor = (id: string) => {
    const qs = new URLSearchParams(params.toString());
    qs.set("c", id);
    return `${base}?${qs.toString()}`;
  };

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-1 flex-col px-4 py-6 md:px-6">
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          <Button variant="secondary" onClick={() => void list.refetch()} loading={list.isRefetching && !list.isFetchingNextPage}>
            <RefreshCw />
            {t("refresh")}
          </Button>
        }
      />
      <Card className="mb-4 p-3">
        <form className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" onSubmit={(e) => e.preventDefault()} aria-label={t("filters.label")}>
          <Field label={t("filters.search")} htmlFor="inbox-q">
            <Input id="inbox-q" type="search" value={search} maxLength={200} placeholder={t("filters.searchPlaceholder")} onChange={(e) => setSearch(e.target.value)} />
          </Field>
          <Field label={t("filters.provider")} htmlFor="inbox-provider">
            <Select
              id="inbox-provider"
              aria-label={t("filters.provider")}
              value={provider || "all"}
              onValueChange={(v) => setParam("provider", v)}
              options={[
                { value: "all", label: tc("all") },
                ...[...new Set([...facets.map((f) => f.provider), ...(provider ? [provider] : [])])].map((p) => ({
                  value: p,
                  label: `${label(p)}${facets.find((f) => f.provider === p) ? ` (${facets.find((f) => f.provider === p)?.count})` : ""}`,
                })),
              ]}
            />
          </Field>
          <Field label={t("filters.channel")} htmlFor="inbox-channel">
            <Select
              id="inbox-channel"
              aria-label={t("filters.channel")}
              value={channel || "all"}
              onValueChange={(v) => setParam("channel", v)}
              options={[{ value: "all", label: tc("all") }, ...(channels.data ?? []).map((c) => ({ value: c.id, label: c.name }))]}
            />
          </Field>
          <Field label={t("filters.status")} htmlFor="inbox-status">
            <Select
              id="inbox-status"
              aria-label={t("filters.status")}
              value={status || "all"}
              onValueChange={(v) => setParam("status", v)}
              options={[
                { value: "all", label: tc("all") },
                { value: "open", label: t("statuses.open") },
                { value: "closed", label: t("statuses.closed") },
              ]}
            />
          </Field>
        </form>
        {anyFilter ? (
          <div className="mt-2 flex justify-end">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setSearch("");
                router.replace(pathname, { scroll: false });
              }}
            >
              <FilterX />
              {t("filters.clear")}
            </Button>
          </div>
        ) : null}
      </Card>

      <Card className="grid min-h-[32rem] flex-1 overflow-hidden lg:grid-cols-[minmax(18rem,22rem)_1fr]">
        <div className={cn("flex min-h-0 flex-col border-border lg:border-r", selected && "hidden lg:flex")}>
          {list.isLoading ? (
            <div className="p-4">
              <SkeletonRows rows={8} />
            </div>
          ) : list.error ? (
            <div className="p-4">
              <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void list.refetch()} retryLabel={tc("retry")} />
            </div>
          ) : items.length === 0 ? (
            <div className="p-4">
              <EmptyState
                icon={<InboxIcon />}
                title={anyFilter ? t("empty.filteredTitle") : t("empty.title")}
                description={anyFilter ? t("empty.filteredDescription") : t("empty.description")}
                action={
                  anyFilter ? undefined : (
                    <Button asChild variant="secondary">
                      <Link href={`/app/projects/${projectId}/channels`}>{t("empty.action")}</Link>
                    </Button>
                  )
                }
              />
            </div>
          ) : (
            <>
              <ul className="min-h-0 flex-1 overflow-y-auto" aria-label={t("listLabel")}>
                {items.map((item) => (
                  <Row key={item.id} item={item} active={item.id === selected} href={hrefFor(item.id)} />
                ))}
              </ul>
              <div className="flex items-center justify-between border-t border-border px-3 py-2 text-xs text-fg-muted">
                <span className="tabular">{t("shown", { count: items.length })}</span>
                {list.hasNextPage ? (
                  <Button size="sm" variant="secondary" loading={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()}>
                    {t("loadMore")}
                  </Button>
                ) : null}
              </div>
            </>
          )}
        </div>
        <div className={cn("flex min-h-0 flex-col", !selected && "hidden lg:flex")}>
          {selected ? (
            <>
              <div className="border-b border-border px-4 py-2 lg:hidden">
                <Link href={backHref} className="text-sm text-fg-muted hover:text-fg">
                  {t("backToList")}
                </Link>
              </div>
              <ConversationView key={selected} conversationId={selected} projectId={projectId} canBuild={canBuild} />
            </>
          ) : (
            <div className="flex flex-1 items-center justify-center p-6">
              <EmptyState icon={<MessagesSquare />} title={t("selectTitle")} description={t("selectDescription")} />
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
