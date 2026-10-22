"use client";

import { useParams } from "next/navigation";

import { TraceDetail } from "@/components/traces/trace-detail";

export default function TraceDetailPage() {
  const { id, runId } = useParams<{ id: string; runId: string }>();
  return <TraceDetail key={runId} projectId={id} runId={runId} />;
}
