"use client";

import { cn } from "@messer/ui";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import * as React from "react";

import { api } from "@/lib/api";

import { InterfaceRenderer } from "../renderer/interface-renderer";
import { publicAppSource } from "../source";
import { isHexColor, themeClass, themeStyle } from "../theme";
import type { PublicView } from "../types";
import { PublicLoading, PublicState } from "./public-state";

function Brand({ view }: { view: PublicView }) {
  const logo = view.interface.theme?.logo_url;
  const accent = view.interface.theme?.accent;
  return (
    <div className="flex min-w-0 items-center gap-2.5">
      {logo ? (
        // eslint-disable-next-line @next/next/no-img-element -- customer logo from any https origin
        <img src={logo} alt="" className="h-7 w-auto max-w-32 object-contain" />
      ) : (
        <span aria-hidden className="size-6 shrink-0 rounded-md" style={{ background: isHexColor(accent) ? accent : "var(--accent)" }} />
      )}
      <div className="min-w-0">
        <p className="truncate text-sm font-semibold text-fg">{view.interface.name}</p>
        <p className="truncate text-xs text-fg-muted">{view.org.name}</p>
      </div>
    </div>
  );
}

/** A published app or dashboard at /{org}/{project}/app/{slug} (production data, login when required). */
export function PublicApp({ org, project, slug }: { org: string; project: string; slug: string }) {
  const t = useTranslations("interfaces.public");
  const view = useQuery({
    queryKey: ["public-app", org, project, slug],
    queryFn: () => api<PublicView>(`/api/public/v1/apps/${encodeURIComponent(org)}/${encodeURIComponent(project)}/${encodeURIComponent(slug)}`),
    retry: false,
    refetchOnWindowFocus: false,
  });
  const source = React.useMemo(
    () => publicAppSource(org, project, slug, Boolean(view.data?.viewer.authenticated)),
    [org, project, slug, view.data?.viewer.authenticated],
  );

  React.useEffect(() => {
    if (view.data) document.title = `${view.data.interface.name} · ${view.data.org.name}`;
  }, [view.data]);

  if (view.isPending) return <PublicLoading />;
  if (view.error) return <PublicState error={view.error} onRetry={() => void view.refetch()} />;
  const theme = view.data.interface.theme;
  return (
    <div className={cn("flex min-h-screen flex-col bg-bg text-fg", themeClass(theme))} style={themeStyle(theme)}>
      <header className="sticky top-0 z-10 border-b border-border bg-bg/95 backdrop-blur">
        <div className="mx-auto flex h-14 w-full max-w-7xl items-center justify-between gap-3 px-4">
          <Brand view={view.data} />
          {view.data.viewer.authenticated && view.data.viewer.email ? (
            <span className="hidden truncate text-xs text-fg-muted sm:block">{view.data.viewer.email}</span>
          ) : null}
        </div>
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-4 md:py-6">
        {view.data.interface.description ? <p className="mb-4 text-sm text-fg-muted">{view.data.interface.description}</p> : null}
        <InterfaceRenderer definition={view.data.interface} source={source} />
      </main>
      <footer className="border-t border-border py-3 text-center text-xs text-fg-subtle">{t("poweredBy")}</footer>
    </div>
  );
}
