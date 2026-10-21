import { execSync } from "node:child_process";

import type { TestProject } from "vitest/node";

/**
 * Brings the integration-test database up to the committed schema once per run. Tests then
 * start from empty tables (see `resetDatabase` in tests/db.ts).
 */
export default function setup(project: TestProject): void {
  execSync("pnpm exec prisma migrate deploy", {
    stdio: "pipe",
    env: { ...process.env, ...project.config.env },
  });
}
