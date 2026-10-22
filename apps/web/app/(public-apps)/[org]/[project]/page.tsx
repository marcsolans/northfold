import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { PublicState } from "@/components/interfaces/public/public-state";

type Params = { params: Promise<{ org: string; project: string }> };

export const dynamic = "force-dynamic";
export const metadata: Metadata = { robots: { index: false, follow: false } };

type Landing = { status: "found"; name: string; home: string | null } | { status: "missing" } | { status: "error" };

async function landing(org: string, project: string): Promise<Landing> {
  const api = (process.env.MESSER_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
  try {
    const res = await fetch(
      `${api}/api/public/v1/projects/${encodeURIComponent(org)}/${encodeURIComponent(project)}`,
      { cache: "no-store", signal: AbortSignal.timeout(5000) },
    );
    if (res.status === 404) return { status: "missing" };
    if (!res.ok) return { status: "error" };
    const data = (await res.json()) as { name: string; home: string | null };
    return { status: "found", name: data.name, home: data.home };
  } catch {
    return { status: "error" };
  }
}

/** A project's public address (environment URL): opens its published home interface. */
export default async function PublicProjectPage({ params }: Params) {
  const { org, project } = await params;
  const result = await landing(org, project);
  if (result.status === "found" && result.home) redirect(`/${org}/${project}${result.home}`);
  const kind = result.status === "found" ? "not_deployed" : result.status === "missing" ? "not_found" : "error";
  return <PublicState kind={kind} />;
}
