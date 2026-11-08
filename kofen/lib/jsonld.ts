import { site } from "./site";

/** schema.org Organization. Only facts stated on the site: name, URL, email, cities. */
export function organizationJsonLd(description: string) {
  return {
    "@context": "https://schema.org",
    "@type": "Organization",
    name: site.name,
    url: site.url,
    logo: `${site.url}/icon.svg`,
    email: site.email,
    description,
    location: [
      { "@type": "Place", address: { "@type": "PostalAddress", addressLocality: "Barcelona", addressCountry: "ES" } },
      { "@type": "Place", address: { "@type": "PostalAddress", addressLocality: "San Francisco", addressCountry: "US" } },
    ],
  };
}

/** Serialize for a <script type="application/ld+json">, escaping "<" (Next.js JSON-LD guide). */
export const jsonLdString = (data: unknown) => JSON.stringify(data).replace(/</g, "\\u003c");
