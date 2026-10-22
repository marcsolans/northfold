import { Alert } from "@messer/ui";
import { ArrowLeft, ArrowRight } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { docsNav, getDoc, rewriteDocLink } from "@/lib/content/docs";
import { firstHeading, stripFirstHeading } from "@/lib/content/files";
import { renderMarkdown } from "@/lib/content/markdown";
import { currentLocale, pageMetadata } from "@/lib/marketing/site";

type Params = { params: Promise<{ slug?: string[] }> };

function slugOf(parts: string[] | undefined): string {
  return (parts ?? []).join("/");
}

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const slug = slugOf((await params).slug);
  const locale = await currentLocale();
  const t = await getTranslations("docsSite");
  const doc = getDoc(slug, locale);
  if (!doc) return { title: t("metaTitle") };
  const path = doc.href;
  return pageMetadata({
    title: slug === "" ? t("metaTitle") : `${doc.title} · ${t("title")}`,
    description: doc.description ?? t("metaDescription"),
    path,
    locale,
  });
}

export default async function DocPage({ params }: Params) {
  const slug = slugOf((await params).slug);
  const locale = await currentLocale();
  const t = await getTranslations("docsSite");
  const nav = docsNav(locale);
  if (nav.length === 0 && slug === "") {
    return (
      <div role="alert" className="rounded-md border border-warning/25 bg-warning-soft p-5">
        <p className="text-base font-semibold text-fg">{t("unavailableTitle")}</p>
        <p className="mt-1 text-sm text-fg-muted">{t("unavailableBody")}</p>
      </div>
    );
  }
  const doc = getDoc(slug, locale);
  if (!doc) notFound();

  const body = firstHeading(doc.body) === doc.title ? stripFirstHeading(doc.body) : doc.body;
  const { content, toc } = await renderMarkdown(body, {
    format: doc.format,
    labels: { copy: t("copy"), plainText: t("plainText"), anchor: t("anchor") },
    rewriteLink: rewriteDocLink,
    cacheKey: `docs:${doc.file.path}:${locale}`,
    version: doc.file.mtimeMs,
  });
  const flat = nav.flatMap((s) => s.pages);
  const index = flat.findIndex((p) => p.slug === slug);
  const previous = index > 0 ? flat[index - 1] : undefined;
  const next = index >= 0 && index < flat.length - 1 ? flat[index + 1] : undefined;

  return (
    <div className="grid gap-10 xl:grid-cols-[minmax(0,1fr)_200px]">
      <article lang={doc.fallback ? "es" : locale}>
        <h1 className="text-xl font-semibold leading-tight tracking-tight text-fg">{doc.title}</h1>
        {doc.description ? <p className="mt-2 text-md leading-relaxed text-fg-muted">{doc.description}</p> : null}
        {doc.fallback ? (
          <Alert tone="info" className="mt-4">
            {t("onlySpanish")}
          </Alert>
        ) : null}
        <div className="mt-2 text-[15px]">{content}</div>

        <nav className="mt-12 grid gap-3 border-t border-border pt-6 sm:grid-cols-2" aria-label={`${t("previous")} / ${t("next")}`}>
          {previous ? (
            <Link href={previous.href} className="rounded-md border border-border p-3 hover:bg-subtle">
              <span className="flex items-center gap-1 text-xs text-fg-subtle">
                <ArrowLeft className="size-3.5" aria-hidden />
                {t("previous")}
              </span>
              <span className="mt-1 block text-sm font-medium text-fg">{previous.title}</span>
            </Link>
          ) : (
            <span />
          )}
          {next ? (
            <Link href={next.href} className="rounded-md border border-border p-3 text-right hover:bg-subtle">
              <span className="flex items-center justify-end gap-1 text-xs text-fg-subtle">
                {t("next")}
                <ArrowRight className="size-3.5" aria-hidden />
              </span>
              <span className="mt-1 block text-sm font-medium text-fg">{next.title}</span>
            </Link>
          ) : null}
        </nav>
        <p className="mt-6 text-sm text-fg-muted">
          {t("help")}{" "}
          <Link href="/contact?topic=support" className="font-medium text-fg underline underline-offset-4">
            {t("contact")}
          </Link>
        </p>
      </article>

      {toc.length > 1 ? (
        <aside className="hidden xl:block">
          <div className="sticky top-20">
            <p className="text-xs font-semibold uppercase tracking-wide text-fg-subtle">{t("onThisPage")}</p>
            <ul className="mt-2 flex flex-col gap-1.5 border-l border-border">
              {toc.map((entry) => (
                <li key={entry.id} className={entry.depth === 3 ? "pl-6" : "pl-3"}>
                  <a href={`#${entry.id}`} className="block text-sm leading-snug text-fg-muted hover:text-fg">
                    {entry.text}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </aside>
      ) : null}
    </div>
  );
}
