"use client";

import { useParams } from "next/navigation";

import { ProjectOverview } from "@/components/studio/project-overview";

export default function ProjectOverviewPage() {
  const { id } = useParams<{ id: string }>();
  return <ProjectOverview projectId={id} />;
}
