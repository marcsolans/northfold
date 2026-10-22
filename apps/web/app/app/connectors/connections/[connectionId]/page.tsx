"use client";

import { SkeletonRows } from "@messer/ui";
import { useParams } from "next/navigation";
import * as React from "react";

import { ConnectionDetail } from "@/components/connectors/connection-detail";

export default function ConnectionPage() {
  const params = useParams<{ connectionId: string }>();
  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-6 md:px-8">
      <React.Suspense fallback={<SkeletonRows rows={6} />}>
        <ConnectionDetail connectionId={params.connectionId} />
      </React.Suspense>
    </div>
  );
}
