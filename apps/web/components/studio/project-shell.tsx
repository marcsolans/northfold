"use client";

import { Button, EmptyState, ErrorState, Skeleton, cn } from "@messer/ui";
import { FolderX } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import type * as React from "react";

import { projectHref } from "@/components/shell/nav-config";
import { isNotFound, useProject } from "@/lib/studio/hooks";

import { enabledProjectTabs } from "./project-tabs";

/** Project chrome: breadcrumb, name and the tab bar (only tabs whose pages exist). */
export function ProjectShell({ projectId, children }: { projectId: string; children: React.ReactNode }) {
  const t = useTranslations("projects");
  const tn = useTranslations("nav.project");
  const tc = useTranslations("common");
  const pathname = usePathname();
  const project = useProject(projectId);
  const tabs = enabledProjectTabs();

  if (project.error) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-10 md:px-8">
        {isNotFound(project.error) ? (
          <EmptyState
            icon={<FolderX />}
            title={t("notFound.title")}
            description={t("notFound.description")}
            action={
              <Button asChild variant="secondary">
                <Link href="/app/projects">{t("notFound.back")}</Link>
              </Button>
            }
          />
        ) : (
          <ErrorState
            title={tc("errorTitle")}
            description={tc("errorGeneric")}
            onRetry={() => void project.refetch()}
            retryLabel={tc("retry")}
          />
        )}
      </div>
    );
  }

  const isActive = (href: string, key: string) =>
    key === "overview" ? pathname === href : pathname === href || pathname.startsWith(`${href}/`);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-border bg-bg px-4 md:px-6">
        <div className="flex h-11 items-center gap-2 text-sm">
          <Link href="/app/projects" className="text-fg-muted hover:text-fg">
            {t("title")}
          </Link>
          <span className="text-fg-subtle" aria-hidden>
            /
          </span>
          {project.data ? (
            <Link href={projectHref(projectId, "overview")} className="truncate font-semibold text-fg">
              {project.data.name}
            </Link>
          ) : (
            <Skeleton className="h-4 w-40" />
          )}
        </div>
        <nav className="-mb-px flex gap-1 overflow-x-auto" aria-label={t("tabsLabel")}>
          {tabs.map((key) => {
            const href = projectHref(projectId, key);
            const active = isActive(href, key);
            return (
              <Link
                key={key}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "inline-flex h-9 items-center whitespace-nowrap border-b-2 border-transparent px-2.5 text-sm font-medium text-fg-muted transition-colors hover:text-fg",
                  active && "border-fg text-fg",
                )}
              >
                {tn(key)}
              </Link>
            );
          })}
        </nav>
      </div>
      <div className="flex min-h-0 flex-1 flex-col">{children}</div>
    </div>
  );
}
