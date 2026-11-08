import { headers } from "next/headers";
import { hasLocale } from "next-intl";
import { Link } from "@/i18n/navigation";
import { routing } from "@/i18n/routing";
import { ArrowBox } from "@/components/ui/primitives";

/**
 * Localized 404. The not-found boundary has no params and next-intl's request
 * locale is not available here, so the locale comes from the header the
 * next-intl proxy forwards with every request.
 */
export default async function NotFound() {
  const requested = (await headers()).get("x-next-intl-locale");
  const locale = hasLocale(routing.locales, requested) ? requested : routing.defaultLocale;
  const { ui } = (await import(`@/messages/${locale}.json`)).default;
  return (
    <main
      id="main"
      className="gutter-x flex min-h-[70vh] flex-col items-start justify-center gap-10 py-24"
      style={{ background: "var(--grad-hero)" }}
    >
      <div className="mx-auto flex w-full max-w-[var(--container)] flex-col items-start gap-10">
        <p className="m-0 font-mono text-[11px] uppercase tracking-[0.04em] text-concrete">404</p>
        <h1 className="sheen m-0 text-[length:var(--fs-display)] font-normal leading-[1.04] tracking-[-0.055em]">{ui.notFound.title}</h1>
        <Link href="/" locale={locale} className="btn">
          {ui.notFound.back}
          <ArrowBox />
        </Link>
      </div>
    </main>
  );
}
