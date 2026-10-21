import { expect, test } from "@playwright/test";

import { CUSTOMER, fillSignIn, signUp, STORAGE_STATE } from "./support/accounts";

test.describe("authentication", () => {
  test("a visitor signs up, signs out and signs back in", async ({ page }) => {
    const account = {
      name: "Grace Hopper",
      email: `grace-${Date.now()}@northfold.test`,
      password: "compiler-1952-cobol",
    };
    await signUp(page, account);
    await expect(page).toHaveURL("/account");
    await expect(page.getByText(account.email).first()).toBeVisible();

    await page.getByRole("button", { name: "Sign out" }).filter({ visible: true }).click();
    await expect(page).toHaveURL("/");
    await page.goto("/account");
    await expect(page).toHaveURL("/sign-in?redirectTo=%2Faccount");

    await fillSignIn(page, { email: account.email, password: "not-the-password" });
    await expect(page.getByText("Incorrect email or password.")).toBeVisible();
    await fillSignIn(page, account);
    await expect(page).toHaveURL("/account");
  });

  test("sign-up validates input before calling the server", async ({ page }) => {
    await page.goto("/sign-up");
    await page.getByLabel("Email").fill("not-an-email");
    await page.getByLabel("Password", { exact: true }).fill("short");
    await page.getByLabel("Confirm password").fill("different");
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page.getByText("Enter a valid email address")).toBeVisible();
    await expect(page).toHaveURL("/sign-up");
  });

  test("protected pages send visitors to sign-in and back", async ({ page }) => {
    await page.goto("/account/orders");
    await expect(page).toHaveURL("/sign-in?redirectTo=%2Faccount%2Forders");
    await fillSignIn(page, CUSTOMER);
    await expect(page).toHaveURL("/account/orders");
  });
});

test.describe("as a customer", () => {
  test.use({ storageState: STORAGE_STATE.customer });

  test("the admin is off limits", async ({ page }) => {
    await page.goto("/admin");
    await expect(page).toHaveURL("/");
    await page.goto("/admin/orders");
    await expect(page).toHaveURL("/");
  });
});
