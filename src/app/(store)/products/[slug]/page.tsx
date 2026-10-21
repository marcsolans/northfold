import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { HiChevronRight } from "react-icons/hi2";

import { ProductGallery } from "@/components/store/product-gallery";
import { ProductGrid, ProductGridSkeleton } from "@/components/store/product-card";
import { ProductPurchase } from "@/components/store/product-purchase";
import { SectionHeading } from "@/components/store/section-heading";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { env } from "@/env";
import { formatMoney } from "@/lib/money";
import { CATEGORY_LABELS, categoryHref, PRODUCT_TYPE_LABELS } from "@/lib/navigation";
import { PRICING, STORE } from "@/lib/store-config";
import {
  getProductBySlug,
  getRelatedProducts,
  type ProductDetailDTO,
} from "@/server/queries/catalog";

function summary(description: string): string {
  return description.length > 155 ? `${description.slice(0, 152).trimEnd()}…` : description;
}

export async function generateMetadata({
  params,
}: PageProps<"/products/[slug]">): Promise<Metadata> {
  const { slug } = await params;
  const product = await getProductBySlug(slug);
  if (!product) return { title: "Product not found", robots: { index: false } };
  const image = product.images[0];
  return {
    title: product.name,
    description: summary(product.description),
    alternates: { canonical: `/products/${product.slug}` },
    openGraph: {
      type: "website",
      title: `${product.name} · ${STORE.name}`,
      description: summary(product.description),
      url: `/products/${product.slug}`,
      siteName: STORE.name,
      images: image ? [{ url: image.url, alt: image.alt, width: 1200, height: 1500 }] : [],
    },
    twitter: {
      card: "summary_large_image",
      title: product.name,
      description: summary(product.description),
      images: image ? [image.url] : [],
    },
  };
}

function ProductJsonLd({ product }: { product: ProductDetailDTO }) {
  const data = {
    "@context": "https://schema.org",
    "@type": "Product",
    name: product.name,
    description: product.description,
    image: product.images.map((image) => image.url),
    sku: product.slug,
    brand: { "@type": "Brand", name: STORE.name },
    offers: {
      "@type": "Offer",
      url: `${env.NEXT_PUBLIC_APP_URL}/products/${product.slug}`,
      priceCurrency: STORE.currency.toUpperCase(),
      price: product.price,
      availability: product.inStock
        ? "https://schema.org/InStock"
        : "https://schema.org/OutOfStock",
    },
  };
  return (
    <script
      type="application/ld+json"
      // JSON-LD is data, not script; "<" is escaped so content can never close the tag.
      dangerouslySetInnerHTML={{ __html: JSON.stringify(data).replace(/</g, "\\u003c") }}
    />
  );
}

async function RelatedProducts({ product }: { product: ProductDetailDTO }) {
  const related = await getRelatedProducts(product, 4);
  if (related.length === 0) return null;
  return (
    <section aria-labelledby="related-heading" className="mt-24">
      <SectionHeading id="related-heading" eyebrow="You may also like" title="Related pieces" />
      <ProductGrid products={related} />
    </section>
  );
}

async function ProductContent({ params }: Pick<PageProps<"/products/[slug]">, "params">) {
  const { slug } = await params;
  const product = await getProductBySlug(slug);
  if (!product) notFound();

  return (
    <>
      <ProductJsonLd product={product} />
      <nav aria-label="Breadcrumb" className="mb-6 text-xs text-muted-foreground">
        <ol className="flex flex-wrap items-center gap-1.5">
          <li>
            <Link href="/shop" className="hover:text-foreground">
              Shop
            </Link>
          </li>
          <li aria-hidden="true">
            <HiChevronRight className="size-3" />
          </li>
          <li>
            <Link href={categoryHref(product.category)} className="hover:text-foreground">
              {CATEGORY_LABELS[product.category]}
            </Link>
          </li>
          <li aria-hidden="true">
            <HiChevronRight className="size-3" />
          </li>
          <li aria-current="page" className="text-foreground">
            {product.name}
          </li>
        </ol>
      </nav>

      <div className="grid gap-10 lg:grid-cols-[1.2fr_1fr] lg:gap-16">
        <ProductGallery images={product.images} productName={product.name} />

        <div className="lg:sticky lg:top-24 lg:self-start">
          <div className="flex items-center gap-2">
            <p className="text-xs font-medium tracking-[0.25em] text-accent uppercase">
              {PRODUCT_TYPE_LABELS[product.productType]}
            </p>
            {product.isBestseller ? <Badge tone="accent">Bestseller</Badge> : null}
          </div>
          <h1 className="mt-3 text-3xl font-light tracking-tight sm:text-4xl">{product.name}</h1>
          <p className="mt-4 text-xl">{formatMoney(product.price)}</p>

          <div className="mt-8">
            <ProductPurchase
              product={{
                id: product.id,
                slug: product.slug,
                name: product.name,
                price: product.price,
                imageUrl: product.images[0]?.url ?? null,
                variants: product.variants,
              }}
            />
          </div>

          <div className="mt-10 space-y-6 border-t border-border pt-8">
            <div>
              <h2 className="text-sm font-medium">Details</h2>
              <p className="mt-2 text-sm leading-relaxed whitespace-pre-line text-muted-foreground">
                {product.description}
              </p>
            </div>
            <div>
              <h2 className="text-sm font-medium">Shipping & payment</h2>
              <ul className="mt-2 space-y-1 text-sm text-muted-foreground">
                <li>
                  Free shipping over {formatMoney(PRICING.freeShippingThreshold, { whole: true })},
                  otherwise {formatMoney(PRICING.flatShippingFee, { whole: true })}.
                </li>
                <li>Pay securely by card, or cash on delivery.</li>
              </ul>
            </div>
          </div>
        </div>
      </div>

      <Suspense fallback={<ProductGridSkeleton count={4} className="mt-24" />}>
        <RelatedProducts product={product} />
      </Suspense>
    </>
  );
}

function ProductSkeleton() {
  return (
    <div aria-busy="true" className="grid gap-10 lg:grid-cols-[1.2fr_1fr] lg:gap-16">
      <Skeleton className="aspect-[4/5] w-full" />
      <div className="space-y-4">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-10 w-3/4" />
        <Skeleton className="h-6 w-24" />
        <Skeleton className="mt-8 h-10 w-48" />
        <Skeleton className="h-11 w-full" />
        <Skeleton className="h-12 w-full" />
      </div>
    </div>
  );
}

export default function ProductPage({ params }: PageProps<"/products/[slug]">) {
  return (
    <div className="mx-auto max-w-7xl px-4 pt-8 pb-16 sm:px-6">
      <Suspense fallback={<ProductSkeleton />}>
        <ProductContent params={params} />
      </Suspense>
    </div>
  );
}
