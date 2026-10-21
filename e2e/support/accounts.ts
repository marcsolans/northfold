import { type Page, expect } from "@playwright/test";

export interface Account {
  name: string;
  email: string;
  password: string;
}

/** Created by global.setup.ts; the admin is promoted by re-running the seed with ADMIN_EMAILS. */
export const CUSTOMER: Account = {
  name: "Ada Lovelace",
  email: "ada@northfold.test",
  password: "analytical-engine-1843",
};
export const ADMIN: Account = {
  name: "Northfold Admin",
  email: "admin@northfold.test",
  password: "northfold-admin-e2e",
};

export const STORAGE_STATE = {
  customer: "e2e/.auth/customer.json",
  admin: "e2e/.auth/admin.json",
} as const;

export async function signUp(page: Page, account: Account, redirectTo = "/account") {
  await page.goto(`/sign-up?redirectTo=${encodeURIComponent(redirectTo)}`);
  await page.getByLabel("Full name").fill(account.name);
  await page.getByLabel("Email").fill(account.email);
  await page.getByLabel("Password", { exact: true }).fill(account.password);
  await page.getByLabel("Confirm password").fill(account.password);
  await page.getByRole("button", { name: "Create account" }).click();
}

export async function signIn(page: Page, account: Account, redirectTo = "/account") {
  await page.goto(`/sign-in?redirectTo=${encodeURIComponent(redirectTo)}`);
  await fillSignIn(page, account);
  await expect(page).toHaveURL(redirectTo);
}

export async function fillSignIn(page: Page, account: Pick<Account, "email" | "password">) {
  await page.getByLabel("Email").fill(account.email);
  await page.getByLabel("Password", { exact: true }).fill(account.password);
  await page.getByRole("button", { name: "Sign in" }).click();
}
