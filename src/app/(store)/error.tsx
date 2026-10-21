"use client";

import { ErrorState } from "@/components/layout/error-state";

export default function StoreError({ error, retry }: { error: unknown; retry: () => void }) {
  return <ErrorState error={error} retry={retry} />;
}
