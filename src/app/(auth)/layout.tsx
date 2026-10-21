import Link from "next/link";

import { Logo } from "@/components/layout/logo";

export default function AuthLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="mx-auto flex w-full max-w-6xl items-center justify-between px-4 py-6 sm:px-6">
        <Logo />
        <Link href="/shop" className="text-sm text-muted-foreground hover:text-foreground">
          Continue shopping
        </Link>
      </header>
      <main className="flex flex-1 items-start justify-center px-4 pt-6 pb-16 sm:items-center sm:px-6 sm:pt-0">
        <div className="w-full max-w-md animate-fade-in">{children}</div>
      </main>
    </div>
  );
}
