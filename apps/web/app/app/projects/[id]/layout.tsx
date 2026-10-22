"use client";

import { useParams } from "next/navigation";
import type * as React from "react";

import { ProjectShell } from "@/components/studio/project-shell";

export default function ProjectLayout({ children }: { children: React.ReactNode }) {
  const { id } = useParams<{ id: string }>();
  return <ProjectShell projectId={id}>{children}</ProjectShell>;
}
