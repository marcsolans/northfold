import Link from "next/link";
import "./globals.css";
import { fontClasses } from "@/lib/fonts";

/** Fallback 404 for paths outside any locale (rare: the proxy prefixes every path). */
export default function RootNotFound() {
  return (
    <html lang="en" className={fontClasses}>
      <body>
        <main className="shell flex min-h-screen flex-col items-start justify-center gap-10" style={{ background: "var(--grad-hero)" }}>
          <p className="m-0 font-mono text-[11px] uppercase tracking-[0.04em] text-concrete">404</p>
          <h1 className="m-0 text-[length:var(--fs-display)] font-normal leading-[1.04] tracking-[-0.055em]">Page not found.</h1>
          <Link href="/" className="btn">
            Back to home
          </Link>
        </main>
      </body>
    </html>
  );
}
