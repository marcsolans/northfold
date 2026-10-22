import { Badge, StatusDot, type StatusTone, cn } from "@messer/ui";
import {
  BookOpen,
  Building2,
  Calendar,
  Cloud,
  Cpu,
  Database,
  FolderOpen,
  Globe,
  HardDrive,
  type LucideIcon,
  Mail,
  MessageSquare,
  Plug,
  Server,
  Users,
  Webhook,
} from "lucide-react";
import { useTranslations } from "next-intl";

const ICONS: Record<string, LucideIcon> = {
  "google-drive": HardDrive,
  gmail: Mail,
  "google-calendar": Calendar,
  onedrive: Cloud,
  sharepoint: FolderOpen,
  outlook: Mail,
  slack: MessageSquare,
  notion: BookOpen,
  hubspot: Users,
  salesforce: Building2,
  database: Database,
  webhook: Webhook,
  globe: Globe,
  mcp: Cpu,
  server: Server,
};

export function ConnectorIcon({ icon, className }: { icon: string | null | undefined; className?: string }) {
  const Icon = (icon ? ICONS[icon] : undefined) ?? Plug;
  return (
    <span
      aria-hidden
      className={cn("inline-flex size-8 shrink-0 items-center justify-center rounded-md border border-border bg-subtle text-fg-muted [&_svg]:size-4", className)}
    >
      <Icon />
    </span>
  );
}

const STATUS_TONES: Record<string, StatusTone> = {
  active: "success",
  success: "success",
  online: "success",
  demo: "info",
  queued: "info",
  running: "info",
  error: "danger",
  revoked: "neutral",
  offline: "neutral",
  pending: "warning",
  idle: "neutral",
};

export function StatusBadge({ status }: { status: string }) {
  const t = useTranslations("connectors.status");
  const tone = STATUS_TONES[status] ?? "neutral";
  const live = status === "running" || status === "online";
  return (
    <Badge tone={tone === "neutral" ? "neutral" : tone === "accent" ? "accent" : tone} className="gap-1.5">
      <StatusDot tone={tone} pulse={live} />
      {t.has(status) ? t(status) : status}
    </Badge>
  );
}
