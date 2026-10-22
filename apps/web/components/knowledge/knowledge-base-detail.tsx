"use client";

import {
  Badge,
  Button,
  ConfirmDialog,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  EmptyState,
  ErrorState,
  PageHeader,
  Skeleton,
  StatusDot,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  toast,
} from "@messer/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  BookOpen,
  Database,
  FileText,
  Layers,
  MoreHorizontal,
  Search,
  Settings,
  ShieldCheck,
  SquareTerminal,
  Trash2,
  Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { ApiError, http } from "@/lib/api";
import { formatNumber, localeTag } from "@/lib/format";
import { useRole } from "@/lib/hooks/use-me";

import { BackupsTab } from "./backups-tab";
import { ChunksTab } from "./chunks-tab";
import { EntitiesTab } from "./entities-tab";
import { FilesTab } from "./files-tab";
import { KbSettingsDialog } from "./kb-settings-dialog";
import { GovernanceBadge } from "./knowledge-base-list";
import { PoliciesTab } from "./policies-tab";
import { errorMessage, formatBytes, kbKeys, useKnowledgeBase } from "./queries";
import { SearchTab } from "./search-tab";
import { SqlTab } from "./sql-tab";
import { TablesTab } from "./tables-tab";
import { useKbEvents } from "./use-kb-events";

const TABS = ["files", "tables", "sql", "chunks", "search", "policies", "entities", "backups"] as const;
type Tab = (typeof TABS)[number];
const ICONS = {
  files: FileText,
  tables: Database,
  sql: SquareTerminal,
  chunks: Layers,
  search: Search,
  policies: ShieldCheck,
  entities: Users,
  backups: Archive,
} as const;

function isTab(value: string | null): value is Tab {
  return value !== null && (TABS as readonly string[]).includes(value);
}

/** Knowledge base screen: files, tables, SQL console, chunks, search, policies, entities and backups. */
export function KnowledgeBaseDetail({ kbId }: { kbId: string }) {
  const t = useTranslations("knowledge");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const qc = useQueryClient();
  const canWrite = useRole("builder");
  const isAdmin = useRole("admin");
  const kb = useKnowledgeBase(kbId);
  const { files: liveFiles, connected } = useKbEvents(kbId);
  const [settingsOpen, setSettingsOpen] = React.useState(false);
  const [deleteOpen, setDeleteOpen] = React.useState(false);

  const tabParam = searchParams.get("tab");
  const tab: Tab = isTab(tabParam) ? tabParam : "files";
  const tableId = searchParams.get("table");

  const navigate = React.useCallback(
    (next: { tab?: Tab; table?: string | null }) => {
      const params = new URLSearchParams(searchParams.toString());
      if (next.tab) params.set("tab", next.tab);
      if (next.table === null) params.delete("table");
      else if (next.table) params.set("table", next.table);
      router.replace(`${pathname}?${params.toString()}`, { scroll: false });
    },
    [pathname, router, searchParams],
  );

  const remove = useMutation({
    mutationFn: () => http.del(`/knowledge-bases/${kbId}`),
    onSuccess: () => {
      toast.success(t("detail.deleted"));
      void qc.invalidateQueries({ queryKey: kbKeys.all });
      router.push("/app/knowledge");
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  if (kb.isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-12 w-80" />
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (kb.error || !kb.data) {
    const notFound = kb.error instanceof ApiError && kb.error.status === 404;
    return notFound ? (
      <EmptyState
        icon={<BookOpen />}
        title={t("detail.notFound")}
        description={t("detail.notFoundHint")}
        action={
          <Button asChild variant="secondary">
            <Link href="/app/knowledge">{t("detail.back")}</Link>
          </Button>
        }
      />
    ) : (
      <ErrorState title={tc("errorTitle")} description={errorMessage(kb.error)} onRetry={() => void kb.refetch()} retryLabel={tc("retry")} />
    );
  }

  const data = kb.data;
  const s = data.stats;
  return (
    <div className="flex flex-col gap-2">
      <PageHeader
        breadcrumbs={
          <Link href="/app/knowledge" className="hover:text-fg">
            {t("title")}
          </Link>
        }
        title={
          <span className="flex items-center gap-2">
            {data.name}
            <GovernanceBadge mode={data.governance_mode} />
          </span>
        }
        description={data.description || undefined}
        actions={
          <>
            <span className="flex items-center gap-1.5 text-xs text-fg-subtle" title={connected ? t("detail.live") : t("detail.offline")}>
              <StatusDot tone={connected ? "success" : "neutral"} pulse={connected && s.files_processing > 0} />
              {connected ? t("detail.live") : t("detail.offline")}
            </span>
            {canWrite ? (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="secondary" size="icon" aria-label={tc("actions")}>
                    <MoreHorizontal />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onSelect={() => setSettingsOpen(true)}>
                    <Settings />
                    {t("detail.settings")}
                  </DropdownMenuItem>
                  {isAdmin ? (
                    <>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem destructive onSelect={() => setDeleteOpen(true)}>
                        <Trash2 />
                        {t("detail.delete")}
                      </DropdownMenuItem>
                    </>
                  ) : null}
                </DropdownMenuContent>
              </DropdownMenu>
            ) : null}
          </>
        }
      />
      <div className="-mt-3 mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fg-muted">
        <span className="tabular">{t("card.files", { count: s.files })}</span>
        <span className="tabular">{t("card.chunks", { count: s.chunks })}</span>
        <span className="tabular">{t("card.tables", { count: s.tables })}</span>
        <span className="tabular">{formatBytes(s.size, locale)}</span>
        <Badge tone="outline" className="font-mono">
          {data.embedding_model} · {formatNumber(data.embedding_dim, locale)}
        </Badge>
      </div>

      <Tabs value={tab} onValueChange={(v) => navigate({ tab: v as Tab, table: null })}>
        <TabsList className="overflow-x-auto">
          {TABS.map((key) => {
            const Icon = ICONS[key];
            return (
              <TabsTrigger key={key} value={key}>
                <Icon aria-hidden />
                {t(`tabs.${key}`)}
                {key === "files" && s.files_processing > 0 ? <Badge tone="info">{s.files_processing}</Badge> : null}
              </TabsTrigger>
            );
          })}
        </TabsList>
        <TabsContent value="files">
          <FilesTab kb={data} canWrite={canWrite} live={liveFiles} onOpenTable={(id) => navigate({ tab: "tables", table: id })} />
        </TabsContent>
        <TabsContent value="tables">
          <TablesTab kb={data} canWrite={canWrite} selectedTableId={tableId} onSelectTable={(id) => navigate({ tab: "tables", table: id })} />
        </TabsContent>
        <TabsContent value="sql">
          <SqlTab kb={data} isAdmin={isAdmin} />
        </TabsContent>
        <TabsContent value="chunks">
          <ChunksTab kb={data} canWrite={canWrite} />
        </TabsContent>
        <TabsContent value="search">
          <SearchTab kb={data} />
        </TabsContent>
        <TabsContent value="policies">
          <PoliciesTab kb={data} isAdmin={isAdmin} />
        </TabsContent>
        <TabsContent value="entities">
          <EntitiesTab kb={data} canWrite={canWrite} />
        </TabsContent>
        <TabsContent value="backups">
          <BackupsTab kb={data} isAdmin={isAdmin} />
        </TabsContent>
      </Tabs>

      <KbSettingsDialog kb={data} open={settingsOpen} onOpenChange={setSettingsOpen} />
      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title={t("detail.deleteConfirm", { name: data.name })}
        description={t("detail.deleteDescription")}
        confirmLabel={t("detail.delete")}
        cancelLabel={tc("cancel")}
        loading={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </div>
  );
}
