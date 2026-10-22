import type { Metadata } from "next";

import { PublicChat } from "@/components/interfaces/public/public-chat";

type Params = { params: Promise<{ org: string; project: string; agent: string }> };

export const metadata: Metadata = { title: "Chat", robots: { index: false, follow: false } };

/**
 * The chat page framed by the widget (`/widget/v1.js`); /embed/* may be framed (see proxy.ts CSP). The site-wide
 * consent banner skips /embed/*: no analytics run inside the widget, and the embedding page owns consent.
 */
export default async function EmbedChatPage({ params }: Params) {
  const { org, project, agent } = await params;
  return (
    <div data-messer-embed="">
      <PublicChat org={org} project={project} agent={agent} embed />
    </div>
  );
}
