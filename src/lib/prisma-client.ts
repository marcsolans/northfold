import { PrismaNeon } from "@prisma/adapter-neon";
import { PrismaPg } from "@prisma/adapter-pg";

import { PrismaClient } from "@/generated/prisma/client";

/** Neon hosts are served through Neon's serverless driver; everything else uses node-postgres. */
export function isNeonUrl(connectionString: string): boolean {
  try {
    return new URL(connectionString).hostname.endsWith(".neon.tech");
  } catch {
    return false;
  }
}

/**
 * Creates a Prisma client with the right driver adapter for the connection string. Shared by
 * the app singleton (`src/lib/prisma.ts`), the seed script and the test harness.
 */
export function createPrismaClient(connectionString: string): PrismaClient {
  const adapter = isNeonUrl(connectionString)
    ? new PrismaNeon({ connectionString })
    : new PrismaPg({ connectionString });
  return new PrismaClient({ adapter });
}
