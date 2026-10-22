"use client";

import { useParams } from "next/navigation";
import { Suspense } from "react";

import { TracesList } from "@/components/traces/traces-list";

export default function TracesPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <Suspense>
      <TracesList projectId={id} />
    </Suspense>
  );
}
