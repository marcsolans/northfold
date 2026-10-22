"use client";

import { useParams } from "next/navigation";
import { Suspense } from "react";

import { ChannelDetail } from "@/components/channels/channel-detail";

export default function ProjectChannelPage() {
  const { id, channelId } = useParams<{ id: string; channelId: string }>();
  return (
    <Suspense>
      <ChannelDetail key={channelId} projectId={id} channelId={channelId} />
    </Suspense>
  );
}
