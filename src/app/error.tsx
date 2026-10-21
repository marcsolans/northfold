"use client";

import { ErrorState } from "@/components/layout/error-state";

/** Catches errors in the route-group layouts themselves (e.g. the store shell). */
export default function RootError({ error, retry }: { error: unknown; retry: () => void }) {
  return (
    <main id="main" className="flex flex-1 items-center">
      <ErrorState error={error} retry={retry} />
    </main>
  );
}
