"use client";

import { useParams } from "next/navigation";

import { WorkflowBuilder } from "@/components/workflows/workflow-builder";

export default function WorkflowBuilderPage() {
  const { id, name } = useParams<{ id: string; name: string }>();
  const decoded = decodeURIComponent(name);
  return <WorkflowBuilder key={`${id}:${decoded}`} projectId={id} name={decoded} />;
}
