import { Button, Logo } from "@messer/ui";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

export default async function LandingPage() {
  const t = await getTranslations("marketing");
  return (
    <main className="mx-auto flex min-h-screen max-w-5xl flex-col justify-center gap-6 px-6">
      <Logo />
      <h1 className="max-w-3xl text-3xl font-semibold leading-tight tracking-tight">{t("heroTitle")}</h1>
      <p className="max-w-2xl text-md text-fg-muted">{t("heroSubtitle")}</p>
      <div className="flex gap-3">
        <Button asChild variant="primary" size="lg">
          <Link href="/signup">{t("ctaPrimary")}</Link>
        </Button>
        <Button asChild variant="secondary" size="lg">
          <Link href="/login">{t("login")}</Link>
        </Button>
      </div>
    </main>
  );
}
