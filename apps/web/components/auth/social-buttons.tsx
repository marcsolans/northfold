"use client";

import { Button, Tooltip } from "@messer/ui";
import { useQuery } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { http } from "@/lib/api";

interface AuthConfig {
  mode: "local" | "supabase";
  providers: { google: boolean; microsoft: boolean };
  sso: boolean;
}

function GoogleIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden>
      <path fill="#4285F4" d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.5h6.5a5.6 5.6 0 0 1-2.4 3.6v3h3.9c2.3-2.1 3.5-5.2 3.5-8.8z" />
      <path fill="#34A853" d="M12 24c3.2 0 6-1.1 8-2.9l-3.9-3c-1.1.7-2.5 1.2-4.1 1.2-3.1 0-5.8-2.1-6.7-5H1.3v3.1A12 12 0 0 0 12 24z" />
      <path fill="#FBBC05" d="M5.3 14.3a7.2 7.2 0 0 1 0-4.6V6.6h-4a12 12 0 0 0 0 10.8l4-3.1z" />
      <path fill="#EA4335" d="M12 4.8c1.8 0 3.3.6 4.6 1.8l3.4-3.4A12 12 0 0 0 1.3 6.6l4 3.1c.9-2.9 3.6-4.9 6.7-4.9z" />
    </svg>
  );
}

function MicrosoftIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden>
      <path fill="#F25022" d="M1 1h10.5v10.5H1z" />
      <path fill="#7FBA00" d="M12.5 1H23v10.5H12.5z" />
      <path fill="#00A4EF" d="M1 12.5h10.5V23H1z" />
      <path fill="#FFB900" d="M12.5 12.5H23V23H12.5z" />
    </svg>
  );
}

export function SocialButtons({ next = "/app" }: { next?: string }) {
  const t = useTranslations("auth");
  const { data } = useQuery({ queryKey: ["auth-config"], queryFn: () => http.get<AuthConfig>("/auth/config") });
  const providers = [
    { key: "google" as const, label: t("google"), icon: <GoogleIcon /> },
    { key: "microsoft" as const, label: t("microsoft"), icon: <MicrosoftIcon /> },
  ];
  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-2 gap-2">
        {providers.map((p) => {
          const enabled = data?.providers[p.key] ?? false;
          const button = (
            <Button
              key={p.key}
              type="button"
              variant="secondary"
              disabled={!enabled}
              className="w-full"
              onClick={() => {
                window.location.href = `/api/v1/auth/oauth/${p.key}/start?next=${encodeURIComponent(next)}`;
              }}
            >
              {p.icon}
              {p.label}
            </Button>
          );
          return enabled ? (
            button
          ) : (
            <Tooltip key={p.key} content={t("providerUnavailable")}>
              <span tabIndex={0} className="block">
                {button}
              </span>
            </Tooltip>
          );
        })}
      </div>
      <Button asChild variant="ghost" size="sm">
        <Link href="/sso">
          <KeyRound />
          {t("sso")}
        </Link>
      </Button>
    </div>
  );
}

export function Divider({ label }: { label: string }) {
  return (
    <div className="my-4 flex items-center gap-3 text-xs text-fg-subtle">
      <span className="h-px flex-1 bg-border" />
      {label}
      <span className="h-px flex-1 bg-border" />
    </div>
  );
}
