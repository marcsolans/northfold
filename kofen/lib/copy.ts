import { getMessages } from "next-intl/server";
import type messages from "@/messages/en.json";
import type { Locale } from "@/i18n/routing";

export type Copy = typeof messages;

/**
 * Typed access to the whole message catalogue for structured copy
 * (lists of scenarios, FAQ items, plans…). Server-only.
 */
export async function getCopy(locale: Locale): Promise<Copy> {
  return (await getMessages({ locale })) as unknown as Copy;
}
