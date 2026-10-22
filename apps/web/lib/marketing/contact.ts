/** Topics accepted by POST /api/v1/contact (shared by the server page and the client form). */
export const CONTACT_TOPICS = ["sales", "enterprise", "support", "security", "partnership", "press", "other"] as const;
export type ContactTopic = (typeof CONTACT_TOPICS)[number];

export function isContactTopic(value: unknown): value is ContactTopic {
  return typeof value === "string" && (CONTACT_TOPICS as readonly string[]).includes(value);
}
