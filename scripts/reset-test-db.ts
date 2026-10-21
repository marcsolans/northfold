/**
 * Empties every table of a *test* database (used before e2e runs). Refuses to touch any
 * database whose name does not end in `_test` or `_e2e`.
 */
import "dotenv/config";

import { createPrismaClient } from "../src/lib/prisma-client";

const url = process.env.DATABASE_URL;
if (!url) {
  console.error("DATABASE_URL is not set.");
  process.exit(1);
}

const database = new URL(url).pathname.replace(/^\//, "");
if (!/_(test|e2e)$/.test(database)) {
  console.error(`Refusing to reset "${database}": only *_test or *_e2e databases can be reset.`);
  process.exit(1);
}

const prisma = createPrismaClient(url);

async function main(): Promise<void> {
  const tables = await prisma.$queryRaw<{ tablename: string }[]>`
    SELECT tablename FROM pg_tables
    WHERE schemaname = 'public' AND tablename <> '_prisma_migrations'
  `;
  if (tables.length > 0) {
    const list = tables.map((t) => `"${t.tablename}"`).join(", ");
    await prisma.$executeRawUnsafe(`TRUNCATE TABLE ${list} RESTART IDENTITY CASCADE`);
  }
  console.info(`Reset ${tables.length} tables in ${database}.`);
}

main()
  .then(() => prisma.$disconnect())
  .catch(async (error: unknown) => {
    console.error(error);
    await prisma.$disconnect();
    process.exit(1);
  });
