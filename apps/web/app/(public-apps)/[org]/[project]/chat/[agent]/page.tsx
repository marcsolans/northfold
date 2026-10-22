import type { Metadata } from "next";

import { PublicChat } from "@/components/interfaces/public/public-chat";

type Params = { params: Promise<{ org: string; project: string; agent: string }> };

export const metadata: Metadata = { title: "Chat", robots: { index: false, follow: false } };

/** Public chat with a published agent (configurable theme, optional login, per-end-user memory). */
export default async function PublicChatPage({ params }: Params) {
  const { org, project, agent } = await params;
  return <PublicChat org={org} project={project} agent={agent} />;
}
