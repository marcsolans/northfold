"use client";

import { useParams } from "next/navigation";

import { DeploymentsPage } from "@/components/deployments/deployments-page";

export default function ProjectDeploymentsPage() {
  const { id } = useParams<{ id: string }>();
  return <DeploymentsPage projectId={id} />;
}
