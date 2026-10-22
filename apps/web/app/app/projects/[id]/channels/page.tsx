"use client";

import { useParams } from "next/navigation";

import { ChannelsPage } from "@/components/channels/channels-page";

export default function ProjectChannelsPage() {
  const { id } = useParams<{ id: string }>();
  return <ChannelsPage projectId={id} />;
}
