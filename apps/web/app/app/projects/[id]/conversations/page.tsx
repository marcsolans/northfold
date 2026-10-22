"use client";

import { useParams } from "next/navigation";
import { Suspense } from "react";

import { Inbox } from "@/components/channels/inbox";

export default function ProjectConversationsPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <Suspense>
      <Inbox projectId={id} />
    </Suspense>
  );
}
