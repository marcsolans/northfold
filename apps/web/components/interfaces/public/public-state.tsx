"use client";

import { Button, Logo, Spinner } from "@messer/ui";
import { Clock, Lock, LogIn, SearchX, ShieldOff, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import type * as React from "react";

import { ApiError } from "@/lib/api";

export type PublicStateKind = "not_deployed" | "login" | "forbidden" | "not_found" | "unavailable" | "error";

type Kind = PublicStateKind;

function kindOf(err: unknown): Kind {
  if (!(err instanceof ApiError)) return "error";
  if (err.status === 409 && err.code === "not_deployed") return "not_deployed";
  if (err.status === 401) return "login";
  if (err.status === 403 && err.code === "org_unavailable") return "unavailable";
  if (err.status === 403) return "forbidden";
  if (err.status === 404) return "not_found";
  if (err.status === 402) return "unavailable";
  return "error";
}

const ICONS: Record<Kind, React.ReactNode> = {
  not_deployed: <Clock className="size-6" aria-hidden />,
  login: <Lock className="size-6" aria-hidden />,
  forbidden: <ShieldOff className="size-6" aria-hidden />,
  not_found: <SearchX className="size-6" aria-hidden />,
  unavailable: <TriangleAlert className="size-6" aria-hidden />,
  error: <TriangleAlert className="size-6" aria-hidden />,
};

/** Friendly full-page states of public apps and chats (not published yet, login, no access, not found…). */
export function PublicState({
  error,
  kind: forced,
  onRetry,
  compact = false,
}: {
  error?: unknown;
  kind?: PublicStateKind;
  onRetry?: () => void;
  compact?: boolean;
}) {
  const t = useTranslations("interfaces.public");
  const kind = forced ?? kindOf(error);
  const next = usePathname() || "/";
  return (
    <div className={compact ? "flex h-full flex-col items-center justify-center p-6" : "flex min-h-screen flex-col bg-subtle"}>
      {!compact ? (
        <header className="px-6 py-5">
          <Link href="/" aria-label="Messer">
            <Logo />
          </Link>
        </header>
      ) : null}
      <main className={compact ? "w-full max-w-sm text-center" : "mx-auto flex w-full max-w-md flex-1 flex-col items-center justify-center px-4 pb-24 text-center"}>
        <div className="mb-3 flex justify-center text-fg-subtle">{ICONS[kind]}</div>
        <h1 className="text-lg font-semibold text-fg">{t(`${kind}.title`)}</h1>
        <p className="mt-2 text-sm text-fg-muted">{t(`${kind}.description`)}</p>
        <div className="mt-5 flex justify-center gap-2">
          {kind === "login" ? (
            <Button asChild variant="primary">
              <a href={`/login?next=${encodeURIComponent(next)}`} target={compact ? "_blank" : undefined} rel="noreferrer">
                <LogIn />
                {t("login.action")}
              </a>
            </Button>
          ) : null}
          {(kind === "error" || kind === "not_deployed") && onRetry ? (
            <Button variant="secondary" onClick={onRetry}>
              {t("retry")}
            </Button>
          ) : null}
        </div>
      </main>
    </div>
  );
}

export function PublicLoading({ compact = false }: { compact?: boolean }) {
  const t = useTranslations("interfaces.public");
  return (
    <div className={compact ? "flex h-full items-center justify-center" : "flex min-h-screen items-center justify-center bg-bg"} role="status" aria-label={t("loading")}>
      <Spinner label={t("loading")} />
    </div>
  );
}
