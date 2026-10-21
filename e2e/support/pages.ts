import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import { STORAGE_STATE } from "./accounts";
import { POPLIN_SHIRT } from "./shop";

const PUBLIC_PAGES = [
  "/",
  "/shop",
  "/shop?category=men&sort=price-asc",
  `/products/${POPLIN_SHIRT.slug}`,
  "/cart",
  "/sign-in",
  "/sign-up",
  "/this-page-does-not-exist",
];
const CUSTOMER_PAGES = [
  "/account",
  "/account/orders",
  "/account/addresses",
  "/account/profile",
  "/checkout",
];
const ADMIN_PAGES = [
  "/admin",
  "/admin/products",
  "/admin/products/new",
  "/admin/orders",
  "/admin/customers",
];

/** No horizontal scrolling, and no serious or critical WCAG 2.1 A/AA violations. */
async function checkPage(page: Page, path: string) {
  await page.goto(path);
  await expect(page.locator("h1").filter({ visible: true }).first()).toBeVisible();
  await page.waitForLoadState("networkidle");

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, `${path} scrolls horizontally`).toBeLessThanOrEqual(0);

  const { violations } = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const blocking = violations
    .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
    .map((violation) => `${violation.id}: ${violation.nodes.map((n) => n.target).join(" | ")}`);
  expect(blocking, `${path} has accessibility violations`).toEqual([]);
}

/** Registers one test per page, for the viewport of the project that runs the spec. */
export function definePageChecks() {
  for (const path of PUBLIC_PAGES) {
    test(`${path} fits the screen and is accessible`, async ({ page }) => {
      await checkPage(page, path);
    });
  }

  test.describe("signed in", () => {
    test.use({ storageState: STORAGE_STATE.customer });
    for (const path of CUSTOMER_PAGES) {
      test(`${path} fits the screen and is accessible`, async ({ page }) => {
        await checkPage(page, path);
      });
    }
  });

  test.describe("admin", () => {
    test.use({ storageState: STORAGE_STATE.admin });
    for (const path of ADMIN_PAGES) {
      test(`${path} fits the screen and is accessible`, async ({ page }) => {
        await checkPage(page, path);
      });
    }
  });
}
