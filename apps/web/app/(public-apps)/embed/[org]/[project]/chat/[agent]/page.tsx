import type { Metadata } from "next";

import { PublicChat } from "@/components/interfaces/public/public-chat";

type Params = { params: Promise<{ org: string; project: string; agent: string }> };

export const metadata: Metadata = { title: "Chat", robots: { index: false, follow: false } };

// Inside the widget iframe no analytics run without consent, so the site-wide consent banner is not shown
// (it would cover the chat composer of every embedding page).
const EMBED_CSS = 'body:has([data-messer-embed]) [role="dialog"][aria-live="polite"]{display:none}';

/** The chat page framed by the widget (`/widget/v1.js`); /embed/* may be framed (see proxy.ts CSP). */
export default async function EmbedChatPage({ params }: Params) {
  const { org, project, agent } = await params;
  return (
    <div data-messer-embed="">
      <style>{EMBED_CSS}</style>
      <PublicChat org={org} project={project} agent={agent} embed />
    </div>
  );
}
