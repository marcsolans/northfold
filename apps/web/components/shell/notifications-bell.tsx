"use client";

import { Button, Popover, PopoverContent, PopoverTrigger, cn } from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { http } from "@/lib/api";
import { formatRelative, localeTag } from "@/lib/format";

export interface NotificationItem {
  id: string;
  kind: string;
  payload: { title?: string; body?: string; url?: string };
  read_at: string | null;
  created_at: string;
}

export function NotificationsBell() {
  const t = useTranslations("nav");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["notifications"],
    queryFn: () => http.get<{ items: NotificationItem[]; unread: number }>("/notifications", { limit: 20 }),
    refetchInterval: 30_000,
  });
  const markAll = useMutation({
    mutationFn: () => http.post("/notifications/read-all"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  });
  const markOne = useMutation({
    mutationFn: (id: string) => http.post(`/notifications/${id}/read`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  });
  const unread = data?.unread ?? 0;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={t("notifications")} className="relative">
          <Bell />
          {unread > 0 ? (
            <span className="tabular absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[10px] font-semibold text-accent-fg">
              {unread > 99 ? "99+" : unread}
            </span>
          ) : null}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-0">
        <div className="flex items-center justify-between border-b border-border px-3 py-2">
          <span className="text-sm font-semibold">{t("notifications")}</span>
          {unread > 0 ? (
            <button type="button" className="text-xs text-fg-muted hover:text-fg" onClick={() => markAll.mutate()}>
              {t("markAllRead")}
            </button>
          ) : null}
        </div>
        <div className="max-h-96 overflow-y-auto">
          {(data?.items ?? []).length === 0 ? (
            <p className="px-3 py-6 text-center text-sm text-fg-subtle">{t("notificationsEmpty")}</p>
          ) : (
            data?.items.map((n) => (
              <Link
                key={n.id}
                href={n.payload.url ?? "/app"}
                onClick={() => !n.read_at && markOne.mutate(n.id)}
                className={cn("block border-b border-border px-3 py-2 last:border-0 hover:bg-subtle", !n.read_at && "bg-accent-soft/40")}
              >
                <p className="text-sm font-medium">{n.payload.title ?? n.kind}</p>
                {n.payload.body ? <p className="line-clamp-2 text-xs text-fg-muted">{n.payload.body}</p> : null}
                <p className="mt-0.5 text-[11px] text-fg-subtle">{formatRelative(n.created_at, locale)}</p>
              </Link>
            ))
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
