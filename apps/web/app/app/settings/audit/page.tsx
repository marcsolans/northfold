"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  Dialog,
  DialogContent,
  EmptyState,
  ErrorState,
  Field,
  Input,
  PageHeader,
  Select,
  SkeletonRows,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
} from "@messer/ui";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Download, ScrollText, X } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { AuditDiff } from "@/components/enterprise/audit-diff";
import type { Member } from "@/components/enterprise/types";
import { apiUrl, http } from "@/lib/api";
import { formatDate, localeTag } from "@/lib/format";
import { useMe, useRole } from "@/lib/hooks/use-me";

interface AuditEntry {
  id: string;
  created_at: string;
  action: string;
  actor_id: string | null;
  actor_email: string | null;
  impersonated_by: string | null;
  api_key_id: string | null;
  entity_type: string | null;
  entity_id: string | null;
  diff: Record<string, unknown>;
  ip: string | null;
}

const PAGE = 100;
const ANY = "__any__";

function useDebounced<T>(value: T, ms = 300): T {
  const [debounced, setDebounced] = React.useState(value);
  React.useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), ms);
    return () => window.clearTimeout(id);
  }, [value, ms]);
  return debounced;
}

/** <input type="date"> value → ISO bound (start or end of that local day). */
function dayBound(value: string, end: boolean): string | undefined {
  if (!value) return undefined;
  const d = new Date(`${value}T${end ? "23:59:59.999" : "00:00:00"}`);
  return Number.isNaN(d.getTime()) ? undefined : d.toISOString();
}

export default function AuditPage() {
  const t = useTranslations("audit");
  const ts = useTranslations("settings.sections");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const me = useMe();
  const isAdmin = useRole("admin");

  const [action, setAction] = React.useState("");
  const [actor, setActor] = React.useState(ANY);
  const [entityType, setEntityType] = React.useState("");
  const [since, setSince] = React.useState("");
  const [until, setUntil] = React.useState("");
  const [selected, setSelected] = React.useState<AuditEntry | null>(null);
  const debouncedAction = useDebounced(action.trim());
  const debouncedEntity = useDebounced(entityType.trim());

  const filters = {
    action: debouncedAction || undefined,
    actor_id: actor === ANY ? undefined : actor,
    entity_type: debouncedEntity || undefined,
    since: dayBound(since, false),
    until: dayBound(until, true),
  };
  const members = useQuery({ queryKey: ["members"], queryFn: () => http.get<Member[]>("/members"), enabled: isAdmin });
  const log = useInfiniteQuery({
    queryKey: ["audit-log", filters],
    queryFn: ({ pageParam }) => http.get<AuditEntry[]>("/audit-log", { ...filters, limit: PAGE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => (last.length === PAGE ? pages.length * PAGE : undefined),
    enabled: isAdmin,
  });
  const rows = (log.data?.pages ?? []).flat();
  const hasFilters = Boolean(action || actor !== ANY || entityType || since || until);
  const csvHref = apiUrl("/audit-log/export.csv", { action: filters.action, since: filters.since, until: filters.until });

  if (me.isLoading) return <SkeletonRows rows={6} />;
  if (!isAdmin) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader title={ts("audit")} description={t("description")} />
        <Alert tone="info">{t("adminOnly")}</Alert>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={ts("audit")}
        description={t("description")}
        actions={
          <Button asChild variant="secondary">
            <a href={csvHref} download>
              <Download />
              {t("export")}
            </a>
          </Button>
        }
      />

      <Card className="p-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Field label={t("filters.action")} htmlFor="audit-action">
            <Input
              id="audit-action"
              value={action}
              placeholder={t("filters.actionPlaceholder")}
              onChange={(e) => setAction(e.target.value)}
            />
          </Field>
          <Field label={t("filters.actor")}>
            <Select
              value={actor}
              onValueChange={setActor}
              options={[
                { value: ANY, label: t("filters.anyActor") },
                ...(members.data ?? []).map((m) => ({ value: m.user_id, label: m.name ? `${m.name} · ${m.email}` : m.email })),
              ]}
            />
          </Field>
          <Field label={t("filters.entityType")} htmlFor="audit-entity">
            <Input id="audit-entity" value={entityType} placeholder="sso_connection" onChange={(e) => setEntityType(e.target.value)} />
          </Field>
          <Field label={t("filters.since")} htmlFor="audit-since">
            <Input id="audit-since" type="date" value={since} max={until || undefined} onChange={(e) => setSince(e.target.value)} />
          </Field>
          <Field label={t("filters.until")} htmlFor="audit-until">
            <Input id="audit-until" type="date" value={until} min={since || undefined} onChange={(e) => setUntil(e.target.value)} />
          </Field>
        </div>
        {hasFilters ? (
          <Button
            variant="ghost"
            size="sm"
            className="mt-2"
            onClick={() => {
              setAction("");
              setActor(ANY);
              setEntityType("");
              setSince("");
              setUntil("");
            }}
          >
            <X />
            {t("filters.clear")}
          </Button>
        ) : null}
      </Card>

      <Card>
        {log.isLoading ? (
          <div className="p-4">
            <SkeletonRows rows={8} />
          </div>
        ) : log.error ? (
          <div className="p-4">
            <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void log.refetch()} />
          </div>
        ) : rows.length === 0 ? (
          <div className="p-4">
            <EmptyState icon={<ScrollText />} title={t("empty")} description={hasFilters ? t("emptyFiltered") : undefined} />
          </div>
        ) : (
          <>
            <Table>
              <THead>
                <tr>
                  <TH className="w-44">{t("columns.when")}</TH>
                  <TH>{t("columns.actor")}</TH>
                  <TH>{t("columns.action")}</TH>
                  <TH className="hidden md:table-cell">{t("columns.entity")}</TH>
                  <TH className="hidden lg:table-cell">{t("columns.ip")}</TH>
                </tr>
              </THead>
              <TBody>
                {rows.map((e) => (
                  <TR
                    key={e.id}
                    tabIndex={0}
                    className="cursor-pointer"
                    onClick={() => setSelected(e)}
                    onKeyDown={(ev) => {
                      if (ev.key === "Enter" || ev.key === " ") {
                        ev.preventDefault();
                        setSelected(e);
                      }
                    }}
                  >
                    <TD className="tabular whitespace-nowrap text-fg-muted">{formatDate(e.created_at, locale, true)}</TD>
                    <TD className="max-w-56 truncate">
                      {e.actor_email ?? (e.api_key_id ? t("apiKey") : t("system"))}
                      {e.impersonated_by ? <Badge tone="warning" className="ml-1">{t("impersonated")}</Badge> : null}
                    </TD>
                    <TD>
                      <code className="font-mono text-xs">{e.action}</code>
                    </TD>
                    <TD className="hidden max-w-64 truncate text-fg-muted md:table-cell">
                      {e.entity_type ? `${e.entity_type}${e.entity_id ? ` · ${e.entity_id}` : ""}` : "—"}
                    </TD>
                    <TD className="hidden font-mono text-xs text-fg-muted lg:table-cell">{e.ip ?? "—"}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
            <div className="flex items-center justify-between gap-3 border-t border-border px-4 py-2 text-xs text-fg-muted">
              <span>{t("showing", { count: rows.length })}</span>
              {log.hasNextPage ? (
                <Button size="sm" variant="secondary" loading={log.isFetchingNextPage} onClick={() => void log.fetchNextPage()}>
                  {t("loadMore")}
                </Button>
              ) : null}
            </div>
          </>
        )}
      </Card>

      <Dialog open={selected !== null} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent wide title={selected?.action ?? t("diff.title")} description={selected ? formatDate(selected.created_at, locale, true) : undefined}>
          {selected ? (
            <div className="flex flex-col gap-4">
              <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[10rem_1fr]">
                <dt className="text-fg-muted">{t("columns.actor")}</dt>
                <dd className="break-all">{selected.actor_email ?? (selected.api_key_id ? t("apiKey") : t("system"))}</dd>
                {selected.impersonated_by ? (
                  <>
                    <dt className="text-fg-muted">{t("diff.impersonatedBy")}</dt>
                    <dd className="break-all font-mono text-xs">{selected.impersonated_by}</dd>
                  </>
                ) : null}
                <dt className="text-fg-muted">{t("columns.entity")}</dt>
                <dd className="break-all">
                  {selected.entity_type ?? "—"} {selected.entity_id ? <code className="font-mono text-xs">{selected.entity_id}</code> : null}
                </dd>
                <dt className="text-fg-muted">{t("columns.ip")}</dt>
                <dd className="font-mono text-xs">{selected.ip ?? "—"}</dd>
              </dl>
              <AuditDiff diff={selected.diff} />
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}
