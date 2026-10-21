import type { Metadata } from "next";
import { type ReactNode, Suspense } from "react";

import { AdminShell } from "@/components/admin/admin-shell";
import { Skeleton } from "@/components/ui/skeleton";
import { requireAdminPage } from "@/server/auth/session";

export const metadata: Metadata = {
  title: { default: "Admin", template: "%s · Northfold Admin" },
  robots: { index: false, follow: false },
};

/**
 * Redirects non-admins before any admin UI renders. This is a UX gate only: Next.js renders pages
 * in parallel with their layouts, so every admin page calls requireAdminPage() before loading
 * data, and every admin query, Server Action and route handler calls requireAdmin() itself.
 */
async function AdminGate({ children }: { children: ReactNode }) {
  await requireAdminPage();
  return children;
}

function AdminLoading() {
  return (
    <div aria-busy="true" className="space-y-6">
      <Skeleton className="h-9 w-48" />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-28" />
        ))}
      </div>
      <Skeleton className="h-72" />
    </div>
  );
}

export default function AdminLayout({ children }: LayoutProps<"/admin">) {
  return (
    <AdminShell>
      <Suspense fallback={<AdminLoading />}>
        <AdminGate>{children}</AdminGate>
      </Suspense>
    </AdminShell>
  );
}
