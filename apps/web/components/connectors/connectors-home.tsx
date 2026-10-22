"use client";

import { Button, PageHeader, Tabs, TabsContent, TabsList, TabsTrigger, toast } from "@messer/ui";
import { useQueryClient } from "@tanstack/react-query";
import { Server } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { ConnectorCatalog } from "./catalog";
import { ConnectionsList } from "./connections-list";
import { connectorKeys, useConnections } from "./queries";

export function ConnectorsHome() {
  const t = useTranslations("connectors");
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const qc = useQueryClient();
  const connections = useConnections();
  const requested = params.get("tab");
  const hasConnections = (connections.data ?? []).length > 0;
  const tab = requested === "catalog" || requested === "connections" ? requested : hasConnections ? "connections" : "catalog";

  // Return from the provider's OAuth consent screen: ?connected=<id> or ?oauth_error=<code>.
  const connected = params.get("connected");
  const oauthError = params.get("oauth_error");
  React.useEffect(() => {
    if (!connected && !oauthError) return;
    if (connected) {
      toast.success(t("connections.connected"));
      void qc.invalidateQueries({ queryKey: connectorKeys.connections });
      router.replace(`/app/connectors/connections/${connected}`);
    } else if (oauthError) {
      toast.error(t("connections.oauthError", { code: oauthError }));
      router.replace(pathname);
    }
  }, [connected, oauthError, pathname, qc, router, t]);

  const setTab = (value: string) => {
    const next = new URLSearchParams(params.toString());
    next.set("tab", value);
    router.replace(`${pathname}?${next.toString()}`);
  };

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-6 md:px-8">
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          <Button asChild variant="secondary">
            <Link href="/app/connectors/agents">
              <Server />
              {t("agentsButton")}
            </Link>
          </Button>
        }
      />
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="connections">
            {t("tabs.connections")}
            {hasConnections ? <span className="tabular text-xs text-fg-subtle">{connections.data?.length}</span> : null}
          </TabsTrigger>
          <TabsTrigger value="catalog">{t("tabs.catalog")}</TabsTrigger>
        </TabsList>
        <TabsContent value="connections">
          <ConnectionsList onBrowse={() => setTab("catalog")} />
        </TabsContent>
        <TabsContent value="catalog">
          <ConnectorCatalog />
        </TabsContent>
      </Tabs>
    </div>
  );
}
