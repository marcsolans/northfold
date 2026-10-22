"use client";

import { useParams } from "next/navigation";
import { Suspense } from "react";

import { WorkflowsList } from "@/components/workflows/workflows-list";

export default function WorkflowsPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <Suspense>
      <WorkflowsList projectId={id} />
    </Suspense>
  );
}
