"use client";

import { Suspense } from "react";

import { EmailDecision } from "@/components/approvals/email-decision";

export default function ApprovalEmailPage() {
  return (
    <Suspense>
      <EmailDecision />
    </Suspense>
  );
}
