"use client";

import { Badge, cn } from "@messer/ui";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import * as React from "react";

import { api } from "@/lib/api";

import { useDataLabels } from "../labels";
import { ChatView } from "../renderer/chat-view";
import { endUserToken, publicChatSource } from "../source";
import { isHexColor, themeClass, themeStyle } from "../theme";
import type { ComponentDef, PublicView } from "../types";
import { PublicLoading, PublicState } from "./public-state";

/**
 * Public chat with an agent at /{org}/{project}/chat/{agent} (and /embed/… inside the widget). Anonymous end users
 * keep their memory through a signed cookie; embedded pages also keep the signed token (third-party cookies may be
 * blocked) and send it as a header.
 */
export function PublicChat({ org, project, agent, embed = false }: { org: string; project: string; agent: string; embed?: boolean }) {
  const t = useTranslations("interfaces.public");
  const labels = useDataLabels();
  const base = `/api/public/v1/chat/${encodeURIComponent(org)}/${encodeURIComponent(project)}/${encodeURIComponent(agent)}`;
  const view = useQuery({
    queryKey: ["public-chat", org, project, agent, embed],
    queryFn: async () => {
      const token = embed ? endUserToken.read(org, project) : null;
      const data = await api<PublicView>(base, {
        query: embed ? { embed: true } : undefined,
        headers: token ? { "X-Messer-End-User": token } : undefined,
      });
      if (embed && data.end_user_token) endUserToken.write(org, project, data.end_user_token);
      return data;
    },
    retry: false,
    refetchOnWindowFocus: false,
  });
  const source = React.useMemo(() => publicChatSource(org, project, agent, embed), [org, project, agent, embed]);

  React.useEffect(() => {
    if (view.data && !embed) document.title = `${view.data.interface.name} · ${view.data.org.name}`;
  }, [view.data, embed]);

  if (view.isPending) return <PublicLoading compact={embed} />;
  if (view.error) return <PublicState error={view.error} onRetry={() => void view.refetch()} compact={embed} />;

  const definition = view.data.interface;
  const comp: ComponentDef | undefined = definition.screens[0]?.components[0];
  const theme = definition.theme;
  const accent = isHexColor(theme?.accent) ? theme?.accent : undefined;
  if (!comp) return <PublicState error={null} compact={embed} />;

  return (
    <div className={cn("flex flex-col bg-bg text-fg", "h-dvh", themeClass(theme))} style={themeStyle(theme)}>
      <header className={cn("flex shrink-0 items-center gap-2.5 border-b border-border px-4", embed ? "h-12" : "h-14")}>
        {theme?.logo_url ? (
          // eslint-disable-next-line @next/next/no-img-element -- customer logo from any https origin
          <img src={theme.logo_url} alt="" className="h-7 w-auto max-w-32 object-contain" />
        ) : (
          <span aria-hidden className="size-6 shrink-0 rounded-full" style={{ background: accent ?? "var(--accent)" }} />
        )}
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-sm font-semibold">{comp.title || definition.name}</h1>
          <p className="truncate text-xs text-fg-muted">{view.data.org.name}</p>
        </div>
        {view.data.viewer.authenticated ? <Badge tone="outline">{view.data.viewer.email}</Badge> : null}
      </header>
      <main className={cn("mx-auto flex min-h-0 w-full flex-1 flex-col", embed ? "px-3 py-2" : "max-w-3xl px-4 py-4")}>
        <ChatView comp={comp} source={source} labels={labels} className="min-h-0 flex-1" />
      </main>
      <footer className="shrink-0 pb-2 text-center text-[11px] text-fg-subtle">{t("aiNotice")}</footer>
    </div>
  );
}
