"use client";

import { Badge, Button, EmptyState, ErrorState, Input, Skeleton, Tooltip, cn } from "@messer/ui";
import { Search } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { useRole } from "@/lib/hooks/use-me";

import { ConnectDialog } from "./connect-dialog";
import { ConnectorIcon } from "./connector-icon";
import { useCatalog } from "./queries";
import type { ConnectorItem } from "./types";

function useDebounced<T>(value: T, delay = 250): T {
  const [debounced, setDebounced] = React.useState(value);
  React.useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(id);
  }, [value, delay]);
  return debounced;
}

export function ConnectorCatalog() {
  const t = useTranslations("connectors");
  const tc = useTranslations("common");
  const locale = useLocale();
  const canConnect = useRole("builder");
  const [query, setQuery] = React.useState("");
  const [category, setCategory] = React.useState("all");
  const [selected, setSelected] = React.useState<ConnectorItem | null>(null);
  const debounced = useDebounced(query.trim());
  const catalog = useCatalog(debounced, category);
  const categories = catalog.data?.categories ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-center">
        <div className="relative md:w-80">
          <Search className="pointer-events-none absolute left-2.5 top-2 size-4 text-fg-subtle" aria-hidden />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("catalog.search")}
            aria-label={t("catalog.search")}
            className="pl-8"
          />
        </div>
        <div className="flex flex-wrap gap-1" role="tablist" aria-label={t("tabs.catalog")}>
          {[{ key: "all", count: 0 }, ...categories].map((c) => (
            <button
              key={c.key}
              type="button"
              role="tab"
              aria-selected={category === c.key}
              onClick={() => setCategory(c.key)}
              className={cn(
                "h-7 rounded-md border px-2.5 text-xs font-medium transition-colors",
                category === c.key ? "border-fg bg-fg text-bg" : "border-border bg-surface text-fg-muted hover:text-fg",
              )}
            >
              {t(`categories.${c.key}`)}
            </button>
          ))}
        </div>
      </div>

      {catalog.isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-36" />
          ))}
        </div>
      ) : catalog.error ? (
        <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void catalog.refetch()} retryLabel={tc("retry")} />
      ) : (catalog.data?.items ?? []).length === 0 ? (
        <EmptyState icon={<Search />} title={t("catalog.empty")} description={t("catalog.emptyHint")} />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {(catalog.data?.items ?? []).map((c) => (
            <div key={c.key} className="flex flex-col gap-3 rounded-md border border-border bg-surface p-4">
              <div className="flex items-start gap-3">
                <ConnectorIcon icon={c.icon} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <p className="text-base font-semibold text-fg">{c.name}</p>
                    {c.availability.mode === "demo" ? (
                      <Tooltip content={t("catalog.demoHint", { vars: c.availability.missing_env.join(", ") })}>
                        <Badge tone="info" tabIndex={0}>
                          {t("catalog.demo")}
                        </Badge>
                      </Tooltip>
                    ) : null}
                  </div>
                  <p className="text-xs text-fg-subtle">
                    {t(`categories.${c.category}`)} · {t(`authTypes.${c.auth_type}`)}
                  </p>
                </div>
              </div>
              <p className="line-clamp-3 min-h-[3.75em] text-sm text-fg-muted">
                {locale === "en" && c.description_en ? c.description_en : c.description}
              </p>
              <div className="mt-auto flex items-center justify-between gap-2">
                <div className="flex flex-wrap gap-1">
                  {c.capabilities.actions.length > 0 ? (
                    <Badge tone="outline">{t("catalog.actions", { count: c.capabilities.actions.length })}</Badge>
                  ) : null}
                  {c.capabilities.sync ? <Badge tone="outline">{t("catalog.sync")}</Badge> : null}
                  {c.capabilities.events.length > 0 ? <Badge tone="outline">{t("catalog.events")}</Badge> : null}
                  {c.capabilities.agent ? <Badge tone="outline">{t("catalog.agent")}</Badge> : null}
                </div>
                {canConnect ? (
                  <Button size="sm" variant="secondary" onClick={() => setSelected(c)}>
                    {t("catalog.connect")}
                  </Button>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      )}
      <ConnectDialog connector={selected} open={selected !== null} onOpenChange={(open) => !open && setSelected(null)} />
    </div>
  );
}
