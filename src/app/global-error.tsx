"use client";

import { ErrorState } from "@/components/layout/error-state";
import { STORE } from "@/lib/store-config";

import "./globals.css";

/** Replaces the root layout when it fails, so it renders its own document. */
export default function GlobalError({ error, retry }: { error: unknown; retry: () => void }) {
  return (
    <html lang="en">
      <body className="flex min-h-dvh flex-col">
        <title>{`Something went wrong · ${STORE.name}`}</title>
        <main id="main" className="flex flex-1 items-center">
          <ErrorState error={error} retry={retry} />
        </main>
      </body>
    </html>
  );
}
