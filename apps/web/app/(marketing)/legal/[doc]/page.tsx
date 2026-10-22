import { Alert, cn } from "@messer/ui";
import { TriangleAlert } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { Container } from "@/components/marketing/section";
import { LEGAL_DOCS, getLegalDoc, isLegalDoc, rewriteLegalLink } from "@/lib/content/legal";
import { renderMarkdown } from "@/lib/content/markdown";
import { localeTag } from "@/lib/format";
import { currentLocale, pageMetadata } from "@/lib/marketing/site";

type Params = { params: Promise<{ doc: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { doc: key } = await params;
  if (!isLegalDoc(key)) return {};
  const locale = await currentLocale();
  const doc = getLegalDoc(key, locale);
  if (!doc) return {};
  const t = await getTranslations("legal");
  return pageMetadata({
    title: doc.title,
    description: doc.description ?? `${doc.title} · ${t("draftTitle")}`,
    path: `/legal/${key}`,
    locale,
  });
}

export default async function LegalPage({ params }: Params) {
  const { doc: key } = await params;
  if (!isLegalDoc(key)) notFound();
  const locale = await currentLocale();
  const doc = getLegalDoc(key, locale);
  if (!doc) notFound();
  const t = await getTranslations("legal");
  const { content } = await renderMarkdown(doc.body, {
    format: "md",
    labels: { copy: t("copy"), plainText: t("plainText"), anchor: t("anchor") },
    rewriteLink: rewriteLegalLink,
    cacheKey: `legal:${doc.file.path}:${locale}`,
    version: doc.file.mtimeMs,
  });
  const updated = doc.updated
    ? new Intl.DateTimeFormat(localeTag(locale), { dateStyle: "long", timeZone: "UTC" }).format(new Date(`${doc.updated}T00:00:00Z`))
    : null;

  return (
    <Container className="py-10 sm:py-14">
      <div className="grid gap-8 lg:grid-cols-[220px_minmax(0,1fr)] lg:gap-12">
        <aside className="lg:sticky lg:top-20 lg:self-start">
          <nav aria-label={t("otherDocs")}>
            <p className="px-2 text-xs font-semibold uppercase tracking-wide text-fg-subtle">{t("otherDocs")}</p>
            <ul className="mt-2 flex gap-1 overflow-x-auto pb-1 lg:flex-col lg:gap-px lg:overflow-visible">
              {LEGAL_DOCS.map((other) => (
                <li key={other} className="shrink-0">
                  <Link
                    href={`/legal/${other}`}
                    aria-current={other === key ? "page" : undefined}
                    className={cn(
                      "block whitespace-nowrap rounded-md px-2 py-1.5 text-sm",
                      other === key ? "bg-subtle font-medium text-fg" : "text-fg-muted hover:bg-subtle hover:text-fg",
                    )}
                  >
                    {t(`docs.${other}`)}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        </aside>
        <article className="min-w-0 max-w-3xl" lang={doc.fallback ? "es" : locale}>
          <div role="note" className="flex gap-3 rounded-md border border-warning/30 bg-warning-soft px-4 py-3">
            <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
            <div>
              <p className="text-sm font-semibold text-fg">{t("draftTitle")}</p>
              <p className="text-sm text-fg-muted">{t("draftBody")}</p>
            </div>
          </div>
          <h1 className="mt-8 text-xl font-semibold leading-tight tracking-tight text-fg">{doc.title}</h1>
          <p className="mt-2 text-sm text-fg-subtle">
            {updated ? t("updated", { date: updated }) : null}
            {updated && doc.version ? " · " : null}
            {doc.version ? t("version", { version: doc.version }) : null}
          </p>
          {doc.fallback ? (
            <Alert tone="info" className="mt-4">
              {t("onlySpanish")}
            </Alert>
          ) : null}
          <div className="mt-4 text-[15px]">{content}</div>
          <p className="mt-10 border-t border-border pt-6 text-sm text-fg-muted">
            {t("questions")}{" "}
            <Link href="/contact?topic=other" className="font-medium text-fg underline underline-offset-4">
              {t("contact")}
            </Link>
          </p>
        </article>
      </div>
    </Container>
  );
}
