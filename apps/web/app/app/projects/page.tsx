"use client";

import { Button, Card, EmptyState, ErrorState, PageHeader, Skeleton } from "@messer/ui";
import { Bot, FolderKanban, Plus, Sparkles, Workflow, Zap } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";
import { Suspense } from "react";

import { CreateProjectDialog } from "@/components/studio/create-project-dialog";
import { formatNumber, formatRelative, localeTag } from "@/lib/format";
import { useRole } from "@/lib/hooks/use-me";
import { useProjects } from "@/lib/studio/hooks";

function ProjectsList() {
  const t = useTranslations("projects");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const canCreate = useRole("builder");
  const projects = useProjects();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const [open, setOpen] = React.useState(false);

  React.useEffect(() => {
    if (params.get("new") === "1" && canCreate) {
      setOpen(true);
      router.replace(pathname);
    }
  }, [params, canCreate, router, pathname]);

  const createButton = canCreate ? (
    <Button variant="primary" onClick={() => setOpen(true)}>
      <Plus />
      {t("new")}
    </Button>
  ) : null;

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-8 md:px-8">
      <PageHeader title={t("title")} description={t("description")} actions={createButton} />
      {projects.isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" role="status" aria-label={tc("loading")}>
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-36" />
          ))}
        </div>
      ) : projects.error ? (
        <ErrorState
          title={tc("errorTitle")}
          description={tc("errorGeneric")}
          onRetry={() => void projects.refetch()}
          retryLabel={tc("retry")}
        />
      ) : (projects.data ?? []).length === 0 ? (
        <EmptyState
          icon={<FolderKanban />}
          title={t("empty.title")}
          description={t("empty.description")}
          action={
            <div className="flex flex-wrap justify-center gap-2">
              {createButton}
              <Button asChild variant="secondary">
                <Link href="/app">
                  <Sparkles />
                  {t("empty.composer")}
                </Link>
              </Button>
            </div>
          }
        />
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {(projects.data ?? []).map((p) => (
            <li key={p.id}>
              <Card className="h-full transition-colors hover:border-border-strong">
                <Link href={`/app/projects/${p.id}`} className="flex h-full flex-col gap-3 p-4">
                  <div className="min-w-0">
                    <h2 className="truncate text-base font-semibold">{p.name}</h2>
                    <p className="mt-1 line-clamp-2 min-h-10 text-sm text-fg-muted">
                      {p.description || <span className="text-fg-subtle">{t("noDescription")}</span>}
                    </p>
                  </div>
                  <dl className="mt-auto grid grid-cols-3 gap-2 text-xs text-fg-muted">
                    <div className="flex items-center gap-1.5">
                      <Bot className="size-3.5" aria-hidden />
                      <dt className="sr-only">{t("stats.agents")}</dt>
                      <dd className="tabular">{t("stats.agentsCount", { count: p.agents })}</dd>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <Workflow className="size-3.5" aria-hidden />
                      <dt className="sr-only">{t("stats.workflows")}</dt>
                      <dd className="tabular">{t("stats.workflowsCount", { count: p.workflows })}</dd>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <Zap className="size-3.5" aria-hidden />
                      <dt className="sr-only">{t("stats.runs")}</dt>
                      <dd className="tabular">{t("stats.runsCount", { count: p.runs_30d, value: formatNumber(p.runs_30d, locale) })}</dd>
                    </div>
                  </dl>
                  <p className="border-t border-border pt-2 text-xs text-fg-subtle">
                    {t("updated", { when: formatRelative(p.updated_at, locale) })}
                  </p>
                </Link>
              </Card>
            </li>
          ))}
        </ul>
      )}
      <CreateProjectDialog open={open} onOpenChange={setOpen} />
    </div>
  );
}

export default function ProjectsPage() {
  return (
    <Suspense>
      <ProjectsList />
    </Suspense>
  );
}
