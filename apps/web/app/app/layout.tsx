import type { Metadata } from "next";
import type * as React from "react";

import { AppShell } from "@/components/shell/app-shell";

export const metadata: Metadata = { title: "Messer", robots: { index: false } };

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
