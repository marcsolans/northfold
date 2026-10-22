"use client";

import { useParams } from "next/navigation";
import { Suspense } from "react";

import { AgentsList } from "@/components/studio/agents-list";

export default function AgentsPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <Suspense>
      <AgentsList projectId={id} />
    </Suspense>
  );
}
