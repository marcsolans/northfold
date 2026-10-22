"use client";

import { KnowledgeBaseList } from "@/components/knowledge/knowledge-base-list";

export default function KnowledgePage() {
  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-6 md:px-8">
      <KnowledgeBaseList />
    </div>
  );
}
