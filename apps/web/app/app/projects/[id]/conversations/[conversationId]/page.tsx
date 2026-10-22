"use client";

import { useParams } from "next/navigation";
import { Suspense } from "react";

import { Inbox } from "@/components/channels/inbox";

export default function ProjectConversationPage() {
  const { id, conversationId } = useParams<{ id: string; conversationId: string }>();
  return (
    <Suspense>
      <Inbox projectId={id} selectedId={conversationId} />
    </Suspense>
  );
}
