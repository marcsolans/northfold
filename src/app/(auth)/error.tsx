"use client";

import { ErrorState } from "@/components/layout/error-state";

export default function AuthError({ error, retry }: { error: unknown; retry: () => void }) {
  return <ErrorState error={error} retry={retry} className="py-8 sm:py-8" />;
}
