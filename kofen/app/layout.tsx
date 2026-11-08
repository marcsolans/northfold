import type { ReactNode } from "react";

/**
 * Pass-through root layout. The real document (<html lang dir>) is rendered by
 * app/[locale]/layout.tsx; this file only exists so Next.js has a static root for
 * app/not-found.tsx (requests that never reach a locale).
 */
export default function RootLayout({ children }: { children: ReactNode }) {
  return children;
}
