import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { cookies, headers } from "next/headers";
import { getRequestConfig } from "next-intl/server";

import { LOCALE_COOKIE, type Locale, defaultLocale, isLocale } from "./config";

// Messages are split by namespace (messages/<locale>/<namespace>.json) so each area owns its file.
const cache = new Map<Locale, Record<string, unknown>>();

function loadMessages(locale: Locale): Record<string, unknown> {
  const cached = cache.get(locale);
  if (cached && process.env.NODE_ENV === "production") return cached;
  const dir = join(process.cwd(), "messages", locale);
  const messages: Record<string, unknown> = {};
  for (const file of readdirSync(dir)) {
    if (!file.endsWith(".json")) continue;
    messages[file.replace(/\.json$/, "")] = JSON.parse(readFileSync(join(dir, file), "utf8"));
  }
  cache.set(locale, messages);
  return messages;
}

// Spanish is the product language; English is opt-in (language switcher, profile or ?lang=en links).
async function detectLocale(): Promise<Locale> {
  const cookieStore = await cookies();
  const fromCookie = cookieStore.get(LOCALE_COOKIE)?.value;
  if (isLocale(fromCookie)) return fromCookie;
  const forced = (await headers()).get("x-messer-locale");
  return isLocale(forced) ? forced : defaultLocale;
}

export default getRequestConfig(async () => {
  const locale = await detectLocale();
  return {
    locale,
    messages: loadMessages(locale),
    timeZone: "Europe/Madrid",
    now: new Date(),
  };
});
