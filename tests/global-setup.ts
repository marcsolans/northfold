import { execSync } from "node:child_process";

import type { TestProject } from "vitest/node";

/**
 * Brings the integration-test database up to the committed schema once per run. Tests then
 * start from empty tables (see `resetDatabase` in tests/db.ts), so this refuses to run against
 * any database whose name does not end in `_test` or `_e2e`.
 */
export default function setup(project: TestProject): void {
  const url = project.config.env.DATABASE_URL ?? "";
  const database = URL.canParse(url) ? new URL(url).pathname.replace(/^\//, "") : "";
  if (!/_(test|e2e)$/.test(database)) {
    const error = new Error(
      `Refusing to run integration tests against "${database}": every test empties the ` +
        "database, so use a dedicated *_test database (TEST_DATABASE_URL).",
    );
    // Vitest cannot source-map stack frames from a global setup; the message is what matters.
    error.stack = `${error.name}: ${error.message}`;
    throw error;
  }
  execSync("pnpm exec prisma migrate deploy", {
    stdio: "pipe",
    env: { ...process.env, ...project.config.env },
  });
}
