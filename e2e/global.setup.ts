import { execFileSync } from "node:child_process";

import { test as setup, expect, type Page } from "@playwright/test";

import { ADMIN, type Account, CUSTOMER, signIn, signUp, STORAGE_STATE } from "./support/accounts";
import { E2E_DATABASE_URL } from "./support/env";

/** Signs the account up, or signs in when it exists already (a reused local server). */
async function ensureAccount(page: Page, account: Account) {
  await signUp(page, account);
  const outcome = await Promise.race([
    page.waitForURL("/account").then(() => "created" as const),
    page
      .getByText("An account with this email already exists")
      .waitFor()
      .then(() => "exists" as const),
  ]);
  if (outcome === "exists") await signIn(page, account);
}

setup("create the customer and the admin", async ({ browser }) => {
  for (const [account, path] of [
    [CUSTOMER, STORAGE_STATE.customer],
    [ADMIN, STORAGE_STATE.admin],
  ] as const) {
    const context = await browser.newContext();
    const page = await context.newPage();
    await ensureAccount(page, account);
    await context.storageState({ path });
    await context.close();
  }

  // The documented way to create the first admin: sign up, then re-run the seed.
  const output = execFileSync("pnpm", ["exec", "tsx", "prisma/seed.ts"], {
    env: { ...process.env, DATABASE_URL: E2E_DATABASE_URL, ADMIN_EMAILS: ADMIN.email },
    encoding: "utf8",
  });
  expect(output).toContain("Promoted 1 user(s) to ADMIN.");
});
