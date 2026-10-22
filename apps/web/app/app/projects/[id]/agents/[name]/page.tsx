"use client";

import { useParams } from "next/navigation";

import { AgentBuilder } from "@/components/studio/builder/agent-builder";

export default function AgentBuilderPage() {
  const { id, name } = useParams<{ id: string; name: string }>();
  const decoded = decodeURIComponent(name);
  return <AgentBuilder key={`${id}:${decoded}`} projectId={id} name={decoded} />;
}
