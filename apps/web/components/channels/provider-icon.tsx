"use client";

import { Badge, cn } from "@messer/ui";
import {
  Code2,
  Globe,
  Hash,
  type LucideIcon,
  Mail,
  MessageCircle,
  MessagesSquare,
  Mic,
  Phone,
  Send,
  Users,
} from "lucide-react";
import { useTranslations } from "next-intl";

import type { ChannelStatus } from "./types";

const ICONS: Record<string, LucideIcon> = {
  whatsapp: MessageCircle,
  slack: Hash,
  teams: Users,
  telegram: Send,
  email: Mail,
  phone: Phone,
  voice: Mic,
  web: Globe,
  api: Code2,
};

/** Generic icon per provider (no third-party logos). */
export function ProviderIcon({ provider, className, size = "md" }: { provider: string; className?: string; size?: "sm" | "md" }) {
  const Icon = ICONS[provider] ?? MessagesSquare;
  return (
    <span
      aria-hidden
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-md border border-border bg-subtle text-fg-muted",
        size === "sm" ? "size-6 [&_svg]:size-3.5" : "size-8 [&_svg]:size-4",
        className,
      )}
    >
      <Icon />
    </span>
  );
}

export function useProviderLabel() {
  const t = useTranslations("channels.providers");
  return (provider: string) => (t.has(provider) ? t(provider) : provider);
}

const STATUS_TONE = { active: "success", demo: "info", error: "danger", disabled: "neutral" } as const;

export function ChannelStatusBadge({ status }: { status: ChannelStatus }) {
  const t = useTranslations("channels.status");
  return <Badge tone={STATUS_TONE[status] ?? "neutral"}>{t.has(status) ? t(status) : status}</Badge>;
}
