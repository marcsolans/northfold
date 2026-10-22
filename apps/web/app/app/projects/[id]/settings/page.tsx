"use client";

import { useParams } from "next/navigation";

import { ProjectSettings } from "@/components/studio/project-settings";

export default function ProjectSettingsPage() {
  const { id } = useParams<{ id: string }>();
  return <ProjectSettings projectId={id} />;
}
