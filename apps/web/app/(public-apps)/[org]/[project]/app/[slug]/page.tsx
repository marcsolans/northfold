import type { Metadata } from "next";

import { PublicApp } from "@/components/interfaces/public/public-app";

type Params = { params: Promise<{ org: string; project: string; slug: string }> };

export const metadata: Metadata = { title: "App", robots: { index: false, follow: false } };

/** A published interface (app or dashboard) running against production. */
export default async function PublicAppPage({ params }: Params) {
  const { org, project, slug } = await params;
  return <PublicApp org={org} project={project} slug={slug} />;
}
