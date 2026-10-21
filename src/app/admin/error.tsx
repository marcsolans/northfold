"use client";

import { ErrorState } from "@/components/layout/error-state";

export default function AdminError({ error, retry }: { error: unknown; retry: () => void }) {
  return (
    <ErrorState
      error={error}
      retry={retry}
      backHref="/admin"
      backLabel="Admin overview"
      className="py-12 sm:py-16"
    />
  );
}
