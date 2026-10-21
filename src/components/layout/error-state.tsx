"use client";

import Link from "next/link";

import { Button, buttonClasses } from "@/components/ui/button";
import { STORE } from "@/lib/store-config";
import { cn } from "@/lib/utils";

/** Server errors reach the client with only a digest that matches the server log entry. */
function errorDigest(error: unknown): string | undefined {
  if (error instanceof Error && "digest" in error && typeof error.digest === "string") {
    return error.digest;
  }
  return undefined;
}

/** Fallback UI for route error boundaries. Never shows the error message itself. */
export function ErrorState({
  error,
  retry,
  backHref = "/",
  backLabel = "Go home",
  className,
}: {
  error: unknown;
  retry: () => void;
  backHref?: string;
  backLabel?: string;
  className?: string;
}) {
  const digest = errorDigest(error);
  return (
    <div
      className={cn(
        "mx-auto flex max-w-xl flex-col items-center px-4 py-24 text-center sm:py-32",
        className,
      )}
    >
      <p className="text-xs font-medium tracking-[0.3em] text-accent uppercase">Error</p>
      <h1 className="mt-4 text-3xl font-light tracking-tight sm:text-4xl">Something went wrong</h1>
      <p className="mt-4 text-muted-foreground">
        This page could not be loaded. Please try again — if it keeps happening, write to{" "}
        <a href={`mailto:${STORE.supportEmail}`} className="underline underline-offset-4">
          {STORE.supportEmail}
        </a>
        .
      </p>
      {digest ? (
        <p className="mt-3 text-xs text-muted-foreground">
          Reference: <code>{digest}</code>
        </p>
      ) : null}
      <div className="mt-10 flex flex-wrap justify-center gap-3">
        <Button onClick={retry}>Try again</Button>
        <Link href={backHref} className={buttonClasses({ variant: "outline" })}>
          {backLabel}
        </Link>
      </div>
    </div>
  );
}
