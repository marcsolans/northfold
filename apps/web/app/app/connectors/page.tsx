"use client";

import { SkeletonRows } from "@messer/ui";
import * as React from "react";

import { ConnectorsHome } from "@/components/connectors/connectors-home";

export default function ConnectorsPage() {
  return (
    <React.Suspense
      fallback={
        <div className="mx-auto w-full max-w-7xl px-4 py-6 md:px-8">
          <SkeletonRows rows={6} />
        </div>
      }
    >
      <ConnectorsHome />
    </React.Suspense>
  );
}
