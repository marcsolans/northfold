"use client";

import { ErrorState } from "@/components/layout/error-state";

export default function AccountError({ error, retry }: { error: unknown; retry: () => void }) {
  return (
    <ErrorState
      error={error}
      retry={retry}
      backHref="/account"
      backLabel="Account overview"
      className="py-12 sm:py-16"
    />
  );
}
