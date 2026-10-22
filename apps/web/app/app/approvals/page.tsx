"use client";

import { Suspense } from "react";

import { ApprovalsInbox } from "@/components/approvals/approvals-inbox";

export default function ApprovalsPage() {
  return (
    <Suspense>
      <ApprovalsInbox />
    </Suspense>
  );
}
