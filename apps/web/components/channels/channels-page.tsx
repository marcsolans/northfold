"use client";

import { Alert, Badge, Button, Card, Dialog, DialogContent, EmptyState, ErrorState, PageHeader, SkeletonRows } from "@messer/ui";
import { ArrowRight, MessagesSquare, Phone, Plus, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { formatNumber, formatRelative, localeTag } from "@/lib/format";
import { useRole } from "@/lib/hooks/use-me";

import { ConnectChannelDialog } from "./connect-dialog";
import { useChannels } from "./hooks";
import { ChannelStatusBadge, ProviderIcon, useProviderLabel } from "./provider-icon";
import { SetupPanel } from "./setup-panel";
import type { Channel, ChannelCreated } from "./types";

export function channelHref(projectId: string, channelId: string, tab?: string): string {
  return `/app/projects/${projectId}/channels/${channelId}${tab ? `?tab=${tab}` : ""}`;
}

/** Shows the setup instructions (and the secret, once) right after connecting or rotating. */
export function SetupDialog({
  channel,
  secret,
  onClose,
  onContinue,
}: {
  channel: Channel | null;
  secret: string | null;
  onClose: () => void;
  onContinue?: () => void;
}) {
  const t = useTranslations("channels.setup");
  const tc = useTranslations("common");
  return (
    <Dialog open={channel !== null} onOpenChange={(o) => (o ? undefined : onClose())}>
      {channel ? (
        <DialogContent title={t("title", { name: channel.name })} description={t("description")} wide>
          <SetupPanel channel={channel} secret={secret} />
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="secondary" onClick={onClose}>
              {tc("close")}
            </Button>
            {onContinue ? (
              <Button variant="primary" onClick={onContinue}>
                {t("continue")}
                <ArrowRight />
              </Button>
            ) : null}
          </div>
        </DialogContent>
      ) : null}
    </Dialog>
  );
}

function ChannelCard({ channel, projectId }: { channel: Channel; projectId: string }) {
  const t = useTranslations("channels.list");
  const te = useTranslations("channels.environments");
  const locale = localeTag(useLocale());
  const label = useProviderLabel();
  const stats = channel.stats;
  return (
    <Card className="flex flex-col gap-3 p-4">
      <div className="flex items-start gap-3">
        <ProviderIcon provider={channel.provider} />
        <div className="min-w-0 flex-1">
          <Link href={channelHref(projectId, channel.id)} className="block truncate font-semibold text-fg hover:underline">
            {channel.name}
          </Link>
          <p className="truncate text-xs text-fg-muted">
            {label(channel.provider)} · {t("agent", { name: channel.workforce_name ?? "—" })}
          </p>
        </div>
        <ChannelStatusBadge status={channel.status} />
      </div>
      <div className="flex flex-wrap gap-1.5">
        <Badge tone="outline">{te(channel.environment)}</Badge>
        {channel.demo && channel.status !== "demo" ? <Badge tone="info">{t("demo")}</Badge> : null}
        {channel.credential_source === "platform" ? <Badge tone="outline">{t("platformCredentials")}</Badge> : null}
      </div>
      {!channel.supported ? <p className="text-xs text-fg-muted">{t("managedElsewhere")}</p> : null}
      {channel.development_fallback ? (
        <Alert tone="warning" className="py-2 text-xs">
          {t("developmentFallback")}
        </Alert>
      ) : null}
      {channel.status === "error" && channel.error ? (
        <p className="line-clamp-2 text-xs text-danger" title={channel.error}>
          {channel.error}
        </p>
      ) : null}
      <dl className="grid grid-cols-3 gap-2 border-t border-border pt-3 text-xs">
        <div>
          <dt className="text-fg-subtle">{t("conversations")}</dt>
          <dd className="tabular text-sm font-medium">{formatNumber(stats.conversations, locale)}</dd>
        </div>
        <div>
          <dt className="text-fg-subtle">{t("messages24h")}</dt>
          <dd className="tabular text-sm font-medium">{formatNumber(stats.messages_24h, locale)}</dd>
        </div>
        <div>
          <dt className="text-fg-subtle">{t("failed24h")}</dt>
          <dd className={stats.failed_24h ? "tabular text-sm font-medium text-danger" : "tabular text-sm font-medium"}>
            {formatNumber(stats.failed_24h, locale)}
          </dd>
        </div>
      </dl>
      <div className="flex items-center justify-between gap-2 text-xs text-fg-muted">
        <span>{stats.last_message_at ? t("lastMessage", { when: formatRelative(stats.last_message_at, locale) }) : t("noMessages")}</span>
        <span className="flex gap-1.5">
          {channel.supported ? (
            <Button asChild size="sm" variant="secondary">
              <Link href={channelHref(projectId, channel.id, "simulator")}>{t("simulate")}</Link>
            </Button>
          ) : null}
          <Button asChild size="sm" variant="ghost">
            <Link href={channelHref(projectId, channel.id)}>
              {t("open")}
              <ArrowRight />
            </Link>
          </Button>
        </span>
      </div>
    </Card>
  );
}

export function ChannelsPage({ projectId }: { projectId: string }) {
  const t = useTranslations("channels");
  const tc = useTranslations("common");
  const router = useRouter();
  const canBuild = useRole("builder");
  const channels = useChannels(projectId);
  const [connectOpen, setConnectOpen] = React.useState(false);
  const [created, setCreated] = React.useState<ChannelCreated | null>(null);

  const connectButton = canBuild ? (
    <Button variant="primary" onClick={() => setConnectOpen(true)}>
      <Plus />
      {t("connectAction")}
    </Button>
  ) : null;

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-6 md:px-6">
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => void channels.refetch()} loading={channels.isRefetching}>
              <RefreshCw />
              {t("refresh")}
            </Button>
            <Button asChild variant="secondary">
              <Link href={`/app/projects/${projectId}/channels/phone`}>
                <Phone />
                {t("phoneAction")}
              </Link>
            </Button>
            {connectButton}
          </div>
        }
      />
      {channels.isLoading ? (
        <Card className="p-4">
          <SkeletonRows rows={6} />
        </Card>
      ) : channels.error ? (
        <Card className="p-4">
          <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void channels.refetch()} retryLabel={tc("retry")} />
        </Card>
      ) : (channels.data ?? []).length === 0 ? (
        <Card className="p-4">
          <EmptyState icon={<MessagesSquare />} title={t("empty.title")} description={t("empty.description")} action={connectButton} />
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {(channels.data ?? []).map((c) => (
            <ChannelCard key={c.id} channel={c} projectId={projectId} />
          ))}
        </div>
      )}
      <ConnectChannelDialog projectId={projectId} open={connectOpen} onOpenChange={setConnectOpen} onCreated={setCreated} />
      <SetupDialog
        channel={created}
        secret={created?.webhook_secret ?? null}
        onClose={() => setCreated(null)}
        onContinue={
          created
            ? () => {
                const id = created.id;
                setCreated(null);
                router.push(channelHref(projectId, id, created.demo ? "simulator" : undefined));
              }
            : undefined
        }
      />
    </div>
  );
}
