"use client";

import { SkeletonRows } from "@messer/ui";
import { useParams } from "next/navigation";
import * as React from "react";

import { KnowledgeBaseDetail } from "@/components/knowledge/knowledge-base-detail";

export default function KnowledgeBasePage() {
  const params = useParams<{ kbId: string }>();
  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-6 md:px-8">
      <React.Suspense fallback={<SkeletonRows rows={6} />}>
        <KnowledgeBaseDetail kbId={params.kbId} />
      </React.Suspense>
    </div>
  );
}
