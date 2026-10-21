import { execSync } from "node:child_process";

/**
 * Resets the integration-test database once per run: drops everything and re-applies every
 * migration, so tests always start from the committed schema.
 */
export default function setup(): void {
  execSync("pnpm exec prisma migrate reset --force", {
    stdio: "inherit",
    env: { ...process.env, PRISMA_HIDE_UPDATE_MESSAGE: "1" },
  });
}
