import { planOffers } from "./pricing";
import type { PublicPlan } from "./public-api";
import { absoluteUrl } from "./site";

export function organizationLd(description: string): Record<string, unknown> {
  return {
    "@context": "https://schema.org",
    "@type": "Organization",
    "@id": absoluteUrl("/#organization"),
    name: "Messer",
    url: absoluteUrl("/"),
    logo: absoluteUrl("/favicon.svg"),
    description,
    areaServed: "EU",
  };
}

export function softwareApplicationLd(description: string, plans: PublicPlan[] | null): Record<string, unknown> {
  return {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    name: "Messer",
    applicationCategory: "BusinessApplication",
    operatingSystem: "Web",
    url: absoluteUrl("/"),
    description,
    publisher: { "@id": absoluteUrl("/#organization") },
    ...(plans && plans.length ? { offers: planOffers(plans, absoluteUrl("/pricing")) } : {}),
  };
}
