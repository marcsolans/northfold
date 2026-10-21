import { prisma } from "@/lib/prisma";

const TABLES = [
  "order_items",
  "orders",
  "addresses",
  "product_images",
  "product_variants",
  "products",
  "stripe_events",
  "rate_limit_windows",
  "sessions",
  "accounts",
  "verifications",
  "users",
];

/** Empties every application table between tests (the schema itself is reset once per run). */
export async function resetDatabase(): Promise<void> {
  await prisma.$executeRawUnsafe(
    `TRUNCATE TABLE ${TABLES.map((t) => `"${t}"`).join(", ")} RESTART IDENTITY CASCADE`,
  );
}

export { prisma };
