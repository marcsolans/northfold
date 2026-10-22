"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorState,
  Skeleton,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  toast,
} from "@messer/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Inbox, PlugZap, Unplug } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { http } from "@/lib/api";
import { useRole } from "@/lib/hooks/use-me";
import { errorMessage, isNotFound } from "@/lib/studio/hooks";

import { ActivityLog } from "./activity-log";
import { ChannelSettings } from "./channel-settings";
import { channelKeys, useChannel } from "./hooks";
import { ChannelStatusBadge, ProviderIcon, useProviderLabel } from "./provider-icon";
import { SetupPanel } from "./setup-panel";
import { Simulator } from "./simulator";
import type { ChannelTest } from "./types";

const TABS = ["simulator", "setup", "activity", "settings"] as const;
type Tab = (typeof TABS)[number];

export function ChannelDetail({ projectId, channelId }: { projectId: string; channelId: string }) {
  const t = useTranslations("channels.detail");
  const te = useTranslations("channels.environments");
  const tc = useTranslations("common");
  const label = useProviderLabel();
  const canBuild = useRole("builder");
  const qc = useQueryClient();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const channel = useChannel(channelId);
  const requested = params.get("tab");
  const tab: Tab = TABS.includes(requested as Tab) ? (requested as Tab) : "simulator";

  const test = useMutation({
    mutationFn: () => http.post<ChannelTest>(`/channels/${channelId}/test`),
    onSuccess: (res) => {
      void qc.invalidateQueries({ queryKey: channelKeys.detail(channelId) });
      void qc.invalidateQueries({ queryKey: channelKeys.list(projectId) });
      if (res.ok) toast.success(res.demo ? t("testDemo") : t("testOk"));
      else toast.error(res.error ?? t("testFailed"));
    },
    onError: (err) => toast.error(errorMessage(err, tc("errorGeneric"))),
  });

  const back = (
    <Link href={`/app/projects/${projectId}/channels`} className="inline-flex items-center gap-1 text-sm text-fg-muted hover:text-fg">
      <ArrowLeft className="size-4" aria-hidden />
      {t("back")}
    </Link>
  );

  if (channel.isLoading) {
    return (
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 px-4 py-6 md:px-6">
        {back}
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-80 w-full" />
      </div>
    );
  }
  if (channel.error || !channel.data) {
    return (
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-4 py-10 md:px-8">
        {back}
        {isNotFound(channel.error) ? (
          <EmptyState icon={<Unplug />} title={t("notFoundTitle")} description={t("notFoundDescription")} />
        ) : (
          <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void channel.refetch()} retryLabel={tc("retry")} />
        )}
      </div>
    );
  }
  const c = channel.data;

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 px-4 py-6 md:px-6">
      {back}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <ProviderIcon provider={c.provider} />
          <div className="min-w-0">
            <h1 className="truncate text-xl font-semibold">{c.name}</h1>
            <p className="text-sm text-fg-muted">
              {label(c.provider)} · {t("agent", { name: c.workforce_name ?? "—" })}
            </p>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              <ChannelStatusBadge status={c.status} />
              <Badge tone="outline">{te(c.environment)}</Badge>
              {c.demo && c.status !== "demo" ? <Badge tone="info">{t("demo")}</Badge> : null}
            </div>
          </div>
        </div>
        <div className="flex gap-2">
          <Button asChild variant="secondary">
            <Link href={`/app/projects/${projectId}/conversations?channel=${c.id}`}>
              <Inbox />
              {t("conversations")}
            </Link>
          </Button>
          {canBuild && c.supported ? (
            <Button variant="secondary" loading={test.isPending} onClick={() => test.mutate()}>
              <PlugZap />
              {t("test")}
            </Button>
          ) : null}
        </div>
      </div>

      {c.development_fallback ? (
        <Alert tone="warning" title={t("fallbackTitle")}>
          {t("fallbackBody")}
        </Alert>
      ) : null}
      {c.status === "error" && c.error ? (
        <Alert tone="danger" title={t("errorTitle")}>
          {c.error}
        </Alert>
      ) : null}
      {c.status === "disabled" ? <Alert tone="info">{t("disabledBody")}</Alert> : null}

      <Tabs
        value={tab}
        onValueChange={(v) => {
          const next = new URLSearchParams(params.toString());
          next.set("tab", v);
          router.replace(`${pathname}?${next.toString()}`, { scroll: false });
        }}
      >
        <TabsList>
          {TABS.map((key) => (
            <TabsTrigger key={key} value={key} disabled={!c.supported && key === "simulator"}>
              {t(`tabs.${key}`)}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="simulator" className="pt-4">
          {c.supported ? <Simulator channel={c} projectId={projectId} canBuild={canBuild} /> : <Alert tone="info">{t("unsupported")}</Alert>}
        </TabsContent>
        <TabsContent value="setup" className="pt-4">
          <Card>
            <CardHeader title={t("setupTitle")} description={t("setupDescription")} />
            <CardBody>{c.supported ? <SetupPanel channel={c} /> : <Alert tone="info">{t("unsupported")}</Alert>}</CardBody>
          </Card>
        </TabsContent>
        <TabsContent value="activity" className="pt-4">
          <ActivityLog channel={c} projectId={projectId} />
        </TabsContent>
        <TabsContent value="settings" className="pt-4">
          <ChannelSettings key={c.updated_at} channel={c} projectId={projectId} canBuild={canBuild} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
