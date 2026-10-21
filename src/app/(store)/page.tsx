import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { HiArrowRight } from "react-icons/hi2";

import { ProductGrid } from "@/components/store/product-card";
import { SectionHeading } from "@/components/store/section-heading";
import { buttonClasses } from "@/components/ui/button";
import { Category } from "@/generated/prisma/enums";
import { CATEGORY_IMAGES, HERO_IMAGE, SECONDARY_HERO_IMAGE } from "@/lib/brand-images";
import { formatMoney } from "@/lib/money";
import { CATEGORY_LABELS, categoryHref } from "@/lib/navigation";
import { PRICING, STORE } from "@/lib/store-config";
import { getBestsellers, getFeaturedProducts } from "@/server/queries/catalog";

export const metadata: Metadata = {
  alternates: { canonical: "/" },
};

const VALUES = [
  {
    title: "Natural fibres",
    body: "Organic cotton, European linen and responsibly sourced wool, chosen to soften with wear.",
  },
  {
    title: `Free shipping over ${formatMoney(PRICING.freeShippingThreshold, { whole: true })}`,
    body: `A flat ${formatMoney(PRICING.flatShippingFee, { whole: true })} below that. No surprises at checkout.`,
  },
  {
    title: "Pay your way",
    body: "Secure card payments through Stripe, or cash when your order arrives.",
  },
];

export default async function HomePage() {
  const [featured, bestsellers] = await Promise.all([getFeaturedProducts(4), getBestsellers(4)]);

  return (
    <>
      <section className="mx-auto grid max-w-7xl items-center gap-10 px-4 pt-8 pb-16 sm:px-6 lg:grid-cols-[1fr_1.15fr] lg:gap-16 lg:pt-16 lg:pb-24">
        <div className="order-2 animate-fade-in lg:order-1">
          <p className="text-xs font-medium tracking-[0.3em] text-accent uppercase">
            New season essentials
          </p>
          <h1 className="mt-5 text-4xl leading-[1.08] font-light tracking-tight text-balance sm:text-5xl xl:text-6xl">
            Quiet clothing, made to be lived in.
          </h1>
          <p className="mt-6 max-w-md text-base leading-relaxed text-muted-foreground">
            {STORE.tagline}. Fewer, better pieces in natural fabrics and calm colours.
          </p>
          <div className="mt-9 flex flex-wrap gap-3">
            <Link href="/shop" className={buttonClasses({ size: "lg" })}>
              Shop the collection
            </Link>
            <Link
              href="/shop?sort=newest"
              className={buttonClasses({ size: "lg", variant: "outline" })}
            >
              New arrivals
            </Link>
          </div>
        </div>
        <div className="relative order-1 aspect-[4/3] overflow-hidden rounded-lg bg-surface lg:order-2 lg:aspect-[5/6]">
          <Image
            src={HERO_IMAGE.src}
            alt={HERO_IMAGE.alt}
            fill
            preload
            sizes="(min-width: 1024px) 55vw, 100vw"
            className="object-cover"
          />
        </div>
      </section>

      <section
        aria-labelledby="categories-heading"
        className="mx-auto max-w-7xl px-4 py-12 sm:px-6"
      >
        <SectionHeading id="categories-heading" eyebrow="Collections" title="Shop by category" />
        <ul className="grid gap-4 sm:grid-cols-3 sm:gap-6">
          {Object.values(Category).map((category) => (
            <li key={category}>
              <Link
                href={categoryHref(category)}
                className="group relative block aspect-[4/3] overflow-hidden rounded-lg bg-surface sm:aspect-[3/4]"
              >
                <Image
                  src={CATEGORY_IMAGES[category].src}
                  alt={CATEGORY_IMAGES[category].alt}
                  fill
                  sizes="(min-width: 640px) 33vw, 100vw"
                  className="object-cover transition-transform duration-700 ease-out group-hover:scale-[1.04]"
                />
                <span className="absolute inset-0 bg-gradient-to-t from-foreground/60 via-foreground/5 to-transparent" />
                <span className="absolute inset-x-0 bottom-0 flex items-center justify-between p-5 text-primary-foreground">
                  <span className="text-xl font-light tracking-tight">
                    {CATEGORY_LABELS[category]}
                  </span>
                  <HiArrowRight
                    aria-hidden="true"
                    className="size-5 transition-transform group-hover:translate-x-1"
                  />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </section>

      {featured.length > 0 ? (
        <section
          aria-labelledby="featured-heading"
          className="mx-auto max-w-7xl px-4 py-12 sm:px-6"
        >
          <SectionHeading
            id="featured-heading"
            eyebrow="Featured"
            title="Pieces we love right now"
            href="/shop"
            linkLabel="View all"
          />
          <ProductGrid products={featured} />
        </section>
      ) : null}

      <section className="mx-auto my-12 max-w-7xl px-4 sm:px-6">
        <div className="grid overflow-hidden rounded-lg bg-surface lg:grid-cols-2">
          <div className="relative aspect-[16/10] lg:aspect-auto">
            <Image
              src={SECONDARY_HERO_IMAGE.src}
              alt={SECONDARY_HERO_IMAGE.alt}
              fill
              sizes="(min-width: 1024px) 50vw, 100vw"
              className="object-cover"
            />
          </div>
          <div className="px-6 py-12 sm:px-12 lg:py-20">
            <p className="text-xs font-medium tracking-[0.3em] text-accent uppercase">
              The Northfold way
            </p>
            <h2 className="mt-4 text-3xl font-light tracking-tight">Made well. Priced honestly.</h2>
            <dl className="mt-10 space-y-8">
              {VALUES.map((value) => (
                <div key={value.title}>
                  <dt className="font-medium">{value.title}</dt>
                  <dd className="mt-1 text-sm leading-relaxed text-muted-foreground">
                    {value.body}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      </section>

      {bestsellers.length > 0 ? (
        <section
          aria-labelledby="bestsellers-heading"
          className="mx-auto max-w-7xl px-4 py-12 sm:px-6"
        >
          <SectionHeading
            id="bestsellers-heading"
            eyebrow="Bestsellers"
            title="Most loved by our customers"
            href="/shop?sort=newest"
            linkLabel="Shop all"
          />
          <ProductGrid products={bestsellers} />
        </section>
      ) : null}
    </>
  );
}
